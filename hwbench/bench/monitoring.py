from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Thread
from typing import Any, Callable

from hwbench.environment.all_smi import AllSMIMonitoring, list_gpus
from hwbench.environment.hardware import BaseHardware
from hwbench.environment.turbostat import Turbostat
from hwbench.environment.vendors.monitoring_device import DeviceError, DeviceNotReady, MonitoringDevice, init_timeout
from hwbench.utils import helpers as h

from .cdu_monitoring import CDUMonitoring
from .monitoring_structs import (
    MonitoringContexts,
    MonitoringData,
    MonitorMetric,
)


def until_ready(device: MonitoringDevice, delays: list[int], deadline: float, stop: Event) -> None:
    """Initialize <device> until it is ready, in contexts of its own: the metrics of the monitoring are
    reset before each benchmark anyway, see Monitoring.preup().

    A device not ready is tried again after one of the <delays> ending before the <deadline> of
    time.monotonic(), drawn at random, as long as the <stop> is not set; the last DeviceNotReady is raised
    then, when no delay ends before the deadline, and at once without <delays>. A DeviceError is raised
    at once.

    The initialize() of an async device runs in an event loop of this thread, the same for all its
    attempts: the Runner creates it on the first coroutine only, never for a synchronous device."""
    with asyncio.Runner() as runner:
        attempt_until_ready(runner, device, delays, deadline, stop)


def attempt_until_ready(
    runner: asyncio.Runner, device: MonitoringDevice, delays: list[int], deadline: float, stop: Event
) -> None:
    """The attempts of until_ready(), the coroutines of an async device run by <runner>."""
    started = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            initialized = device.initialize(MonitoringContexts())
            if inspect.iscoroutine(initialized):
                runner.run(initialized)
            if attempts > 1:
                print(
                    f"Monitoring/{device.get_label()}: ready after {attempts} attempts in {time.monotonic() - started:.0f}s"
                )
            return
        except DeviceNotReady as error:
            if not delays:
                raise
            # Drawn among the delays ending before the deadline: the servers sharing a device keep
            # spreading their attempts until the end
            remaining = deadline - time.monotonic()
            fitting = [delay for delay in delays if delay <= remaining]
            if not fitting:
                raise DeviceNotReady(
                    f"{error}, still after {attempts} attempts in {time.monotonic() - started:.0f}s"
                ) from None
            delay = random.choice(fitting)
            logging.warning(
                f"Monitoring/{device.get_label()}: attempt {attempts} failed, trying again in {delay}s: {error}"
            )
            if stop.wait(delay):
                raise DeviceNotReady(f"{error}, attempts stopped as another device failed") from None


class ThreadWithReturnValue(Thread):
    """A thread class that return target's return value"""

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
        Thread.__init__(self, group, target, name, args, kwargs, daemon=daemon)
        self._return = None

    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self):
        Thread.join(self)
        return self._return


class Monitoring:
    """A class to perform monitoring."""

    def __init__(self, out_dir, config, hardware: BaseHardware, verbose: bool = False):
        self.config = config
        self.out_dir = out_dir
        self.verbose = verbose
        self.hardware = hardware
        self.vendor = hardware.get_vendor()
        self.metrics = MonitoringData()
        self.executor: ThreadWithReturnValue
        self.turbostat: Turbostat | None = None
        self.all_smi: AllSMIMonitoring | None = None
        self.cdu_monitoring = CDUMonitoring(self.vendor.get_cdus())
        self.prepare()

    def __get_metrics(self) -> MonitoringData:
        """Return the actual metrics."""
        return self.metrics

    def prepare(self):
        """Initialize each source of the monitoring, each one in its thread, before the benchmarks.

        A device not ready is tried again until the init_timeout of the environment file, after a delay
        drawn at random from its retry_delay: the servers of a room started together do not come back at
        the same time to a device they share, like a CDU. A device misconfigured, or a source of the
        server failing, stops the attempts of all of them, and hwbench, as a device still not ready."""
        devices = self.devices()
        deadline = time.monotonic() + init_timeout(self.vendor.monitoring_config_file)
        delays = [device.get_retry_delays() for device in devices]
        stop = Event()

        def start(device: MonitoringDevice, delays: list[int]) -> None:
            try:
                until_ready(device, delays, deadline, stop)
            except BaseException:
                # hwbench stops, also on the fatal() of a key missing in the environment file: the other
                # devices have no reason to keep trying
                stop.set()
                raise

        with ThreadPoolExecutor(max_workers=len(devices)) as executor:
            futures = [(device, executor.submit(start, device, delay)) for device, delay in zip(devices, delays)]
        failed = []
        for device, future in futures:
            try:
                future.result()
            except DeviceError as error:
                logging.error(f"Monitoring/{device.get_label()}: {error}")
                failed.append(device.get_label())
        if failed:
            h.fatal(f"Monitoring: {', '.join(failed)} not ready, stopping before the benchmarks")

    def devices(self) -> list[MonitoringDevice]:
        """The sources of the monitoring of this server: turbostat on x86_64, all-smi with GPUs, the BMC,
        the PDUs and the CDUs."""
        devices: list[MonitoringDevice] = []
        if self.hardware.cpu.get_arch() == "x86_64":
            self.turbostat = Turbostat(self.hardware)
            devices.append(self.turbostat)
        # A server without any GPU is perfectly legitimate: a job loading the GPUs already
        # required all-smi, see Benchmarks.check_requirements()
        gpus = list_gpus()
        if gpus:
            self.all_smi = AllSMIMonitoring(gpus)
            devices.append(self.all_smi)
        devices.append(self.vendor.get_bmc())
        devices.extend(self.vendor.get_pdus())
        devices.extend(self.vendor.get_cdus())
        return devices

    def preup(self, precision_s: int):
        """Start turbostat monitoring before a benchmark run.

        This should be called before each benchmark to initialize turbostat
        in background mode. Turbostat will be triggered on-demand via EOL.

        Args:
            precision_s: Sampling interval in seconds (used for timeouts only)
        """
        self.__reset_metrics()
        if self.all_smi:
            # Reinitialize the GPU metrics after the reset, then start the
            # exporter the monitoring loop will poll. Its readers take about
            # 800ms to initialize, so it is only awaited once turbostat is up.
            self.all_smi.reinitialize_metrics()
            if self.verbose:
                print("Monitoring/all-smi: starting the accelerator metrics exporter")
            self.all_smi.start()
        if self.turbostat:
            # Reinitialize turbostat metrics after reset (fast, doesn't run turbostat)
            self.turbostat.reinitialize_metrics()
            if self.verbose:
                print("Monitoring/turbostat: starting background monitoring with EOL-triggered sampling")
            self.turbostat.start_background()
        if self.all_smi:
            self.all_smi.wait_ready()

    def predown(self):
        """Stop turbostat monitoring after a benchmark run.

        This should be called after each benchmark to cleanly shutdown
        the background turbostat process.
        """
        if self.turbostat:
            if self.verbose:
                print("Monitoring/turbostat: stopping background monitoring")
            self.turbostat.stop_background()
        if self.all_smi:
            if self.verbose:
                print("Monitoring/all-smi: stopping the accelerator metrics exporter")
            self.all_smi.stop()

    def __monitor_bmc(self):
        """Monitor the bmc metrics"""
        bmc = self.vendor.get_bmc()
        # The counter of the device adds up the whole run: only save the timeouts of this iteration
        timeouts_before = bmc.timeouts
        bmc.read_metrics(self.metrics.contexts)
        self.metrics.contexts.Monitor.BMC["Timeouts"].add(bmc.timeouts - timeouts_before)

    def __devices_count(self) -> int:
        """The number of devices read at the same time on each iteration: the BMC, each PDU, the CDUs."""
        return 1 + len(self.vendor.get_pdus()) + (1 if self.vendor.get_cdus() else 0)

    def __start_devices_polling(
        self, devices: ThreadPoolExecutor
    ) -> list[tuple[dict[str, MonitorMetric], list[Future]]]:
        """Read the BMC, each PDU and the CDUs at the same time, each in its thread: a slow device only
        delays the iteration by itself, instead of adding to the others. Each device writes its own
        metrics. Returns the monitor metrics of each kind of device, with the futures of the time spent
        reading each of its devices."""
        start_ns = time.monotonic_ns()

        def timed(read: Callable[[], Any]) -> float:
            """The time spent reading a device, in milliseconds."""
            read()
            return (time.monotonic_ns() - start_ns) * 1e-6

        monitor = self.metrics.contexts.Monitor
        polling = [(monitor.BMC, [devices.submit(timed, self.__monitor_bmc)])]
        pdus = self.vendor.get_pdus()
        # The counters of the PDUs before this iteration: their timeouts are saved once all of them are read
        self.__pdu_timeouts_before = sum(pdu.timeouts for pdu in pdus)
        if pdus:
            power_consumption = self.metrics.contexts.PowerConsumption
            futures = [
                devices.submit(timed, functools.partial(pdu.read_power_consumption, power_consumption)) for pdu in pdus
            ]
            polling.append((monitor.PDU, futures))
        # CDU requests share the host loop and its aggregation boundaries.
        if self.vendor.get_cdus():
            polling.append((monitor.CDU, [devices.submit(timed, self.cdu_monitoring.poll)]))
        return polling

    def __compact(self):
        """Compute statistics"""
        # Compact all metrics in contexts
        self.metrics.contexts.compact_all()
        self.cdu_monitoring.compact()

    def monitor(self, precision_s: int, frequency: int, duration_s: int):
        """Method to trigger asynchronous monitoring"""
        self.executor = ThreadWithReturnValue(
            target=self.__monitor,
            args=(precision_s, frequency, duration_s),
        )
        self.executor.start()

    def get_monitor_metrics(self) -> MonitoringData:
        """Returns the metrics from the latest monitoring."""
        if not self.executor:
            raise RuntimeError("Monitoring has not been started")
        return self.executor.join()  # type: ignore

    def __monitor(self, precision_s: int, frequency: int, duration_s: int) -> MonitoringData:
        """Private method to perform the monitoring."""
        start_monitoring_ns = time.monotonic_ns()
        self.cdu_monitoring.reset(self.metrics.contexts)
        self.metrics.cdus = self.cdu_monitoring.data

        # This function will be a thread of self.monitor()
        #
        #  >|                         duration                        |<
        #  >|    precision               |<                           |
        # __|monitor_loop|_______________|monitor_loop|_______________|
        #   |           >| sleep_time_ns |<
        # sleep_time_ns is the time to wait before starting a new monitor_loop
        # If frequency == 2, every two <precision_s> run, maths are computed

        # Set metadata
        self.metrics.metadata.precision = precision_s
        self.metrics.metadata.frequency = frequency
        self.metrics.metadata.iteration_time = frequency * precision_s

        # Initialize monitor metrics
        # Timeouts: the number of Redfish requests not answered in time during an iteration
        self.metrics.contexts.Monitor.BMC = {
            "Polling": MonitorMetric("Polling", "ms"),
            "Timeouts": MonitorMetric("Timeouts", "requests"),
        }
        self.metrics.contexts.Monitor.PDU = {
            "Polling": MonitorMetric("Polling", "ms"),
            "Timeouts": MonitorMetric("Timeouts", "requests"),
        }
        self.metrics.contexts.Monitor.CPU = {"Polling": MonitorMetric("Polling", "ms")}
        if self.vendor.get_cdus():
            self.metrics.contexts.Monitor.CDU = {"Polling": MonitorMetric("Polling", "ms")}
        if self.all_smi:
            self.metrics.contexts.Monitor.GPU = {"Polling": MonitorMetric("Polling", "ms")}

        # When will we hit "duration_s" ?
        end_of_run_ns = start_monitoring_ns + (duration_s * 1e9)
        loops_done = 0
        compact_count = 0

        def next_iter_ns() -> float:
            # When does the next iteration must starts ?
            return start_monitoring_ns + ((loops_done + 1) * precision_s) * 1e9

        # The threads reading the devices, one per device, for the whole run
        with ThreadPoolExecutor(max_workers=self.__devices_count(), thread_name_prefix="monitoring") as devices:
            # monitor_loop
            while True:
                start_time_loop_ns = time.monotonic_ns()

                # Trigger turbostat sample collection at the start of the monitoring loop
                # This allows turbostat to collect metrics while we perform BMC/PDU monitoring
                if self.turbostat:
                    self.turbostat.trigger_sample()

                if loops_done and loops_done % frequency == 0:
                    # At every frequency, the maths are computed
                    self.__compact()
                    compact_count = compact_count + 1

                # The BMC, the PDUs and the CDUs are read at the same time, the GPUs meanwhile
                polling = self.__start_devices_polling(devices)

                if self.all_smi:
                    start_gpu_ns = time.monotonic_ns()
                    self.all_smi.sample()
                    # Let's monitor the time spent at monitoring the GPUs, in milliseconds
                    self.metrics.contexts.Monitor.GPU["Polling"].add((time.monotonic_ns() - start_gpu_ns) * 1e-6)

                # Let's monitor the time spent at monitoring each kind of device, in milliseconds
                for monitor, futures in polling:
                    monitor["Polling"].add(max(future.result() for future in futures))
                # The Redfish requests of all the PDUs not answered in time during this iteration
                if self.vendor.get_pdus():
                    self.metrics.contexts.Monitor.PDU["Timeouts"].add(
                        sum(pdu.timeouts for pdu in self.vendor.get_pdus()) - self.__pdu_timeouts_before
                    )

                # Now retrieve and parse the turbostat sample that was triggered at the start
                if self.turbostat:
                    turbostat_timing = self.turbostat.get_and_parse_sample(precision_s)

                    # Let's monitor the time spent at retrieving the CPU metrics, in milliseconds
                    self.metrics.contexts.Monitor.CPU["Polling"].add((turbostat_timing - start_time_loop_ns) * 1e-6)

                # Based on the time passed, let's compute the amount of sleep time
                # to keep in sync with the expected precision_s
                sleep_time_ns = next_iter_ns() - time.monotonic_ns()  # in nanoseconds
                sleep_time_ms = sleep_time_ns / 1e6  # in milliseconds
                sleep_time = sleep_time_ns / 1e9  # in seconds

                if sleep_time_ms < -5:
                    # The iteration is already late on schedule
                    # Only print a warning message if we are more than 5ms late
                    print(f"Monitoring iteration {loops_done} is {abs(sleep_time_ms):.2f}ms late")

                # If the current time + sleep_time is above the total duration_s (we accept up to 500ms overdue)
                if (time.monotonic_ns() + max(0, sleep_time_ns)) > (end_of_run_ns + 0.5 * 1e9):
                    # We can stop the monitoring, no more measures will be done
                    break

                if sleep_time > 0:
                    # The iteration is on time, let's sleep until the next one
                    time.sleep(sleep_time)

                loops_done = loops_done + 1

        # How much time did we spent in this monitoring loop ?
        completed_time_ns = time.monotonic_ns()
        self.metrics.metadata.monitoring_time = (completed_time_ns - start_monitoring_ns) * 1e-9  # seconds

        # We were supposed to last "duration_s", how close are we from this metric ?
        self.metrics.metadata.overdue_time_ms = ((completed_time_ns - start_monitoring_ns) - (duration_s * 1e9)) * 1e-6

        self.metrics.metadata.samples_count = compact_count

        # And return the final metrics
        return self.__get_metrics()

    def __reset_metrics(self):
        """Reset all metrics to default state"""
        self.metrics = MonitoringData()
        if self.turbostat:
            self.turbostat.monitoring_contexts = self.metrics.contexts
        if self.all_smi:
            self.all_smi.monitoring_contexts = self.metrics.contexts
