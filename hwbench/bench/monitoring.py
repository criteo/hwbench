from __future__ import annotations

import dataclasses
import time
from threading import Thread
from typing import Any

from hwbench.environment.hardware import BaseHardware
from hwbench.environment.turbostat import CPUSTATS, Turbostat
from hwbench.utils import helpers as h

from .monitoring_structs import (
    MonitoringContextKeys,
    MonitoringData,
    MonitorMetric,
)


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

    def __init__(self, out_dir, config, hardware: BaseHardware):
        self.config = config
        self.out_dir = out_dir
        self.hardware = hardware
        self.vendor = hardware.get_vendor()
        self.metrics = MonitoringData()
        self.executor: ThreadWithReturnValue
        self.turbostat: Turbostat | None = None
        self.prepare()

    def __get_metrics(self) -> MonitoringData:
        """Return the actual metrics."""
        return self.metrics

    def prepare(self):
        """Preparing the monitoring"""
        v = self.vendor
        bmc = self.vendor.get_bmc()
        pdus = self.vendor.get_pdus()

        def check_monitoring(source: str, metric_name: MonitoringContextKeys, data: Any):
            if not isinstance(data, dict):
                # Probably a dataclass
                data = dataclasses.asdict(data)

            if not len(data):
                h.fatal(f"Cannot detect {str(metric_name)} metrics")

            print(
                f"Monitoring/{source}: {str(metric_name)} metrics: "
                + ", ".join([f"{len(data[pc])}x{pc}" for pc in data if len(data[pc]) > 0])
            )

        # - checking if the CPU monitoring works
        if self.hardware.cpu.get_arch() == "x86_64":
            print("Monitoring/turbostat: initialize")
            self.turbostat = Turbostat(self.hardware, self.metrics.contexts)
            check_monitoring("turbostat", MonitoringContextKeys.Freq, self.metrics.contexts.Freq)
            if self.turbostat.has(CPUSTATS.IPC):
                check_monitoring("turbostat", MonitoringContextKeys.IPC, self.metrics.contexts.IPC)

        print(f"Monitoring/BMC: initialize {v.name()} vendor with {bmc.get_driver_name()} {bmc.get_detect_string()}")

        for pdu in pdus:
            print(f"Monitoring/PDU: initialize {pdu.get_name()} with {pdu.get_driver_name()} {pdu.get_detect_string()}")

        # - checking if the bmc monitoring works
        # These calls will also initialize the datastructures out of the monitoring loop
        self.vendor.get_bmc().read_thermals(self.metrics.contexts.Thermal)
        check_monitoring("BMC", MonitoringContextKeys.Thermal, self.metrics.contexts.Thermal)

        self.vendor.get_bmc().read_fans(self.metrics.contexts.Fans)
        check_monitoring("BMC", MonitoringContextKeys.Fans, self.metrics.contexts.Fans)

        self.vendor.get_bmc().read_power_consumption(self.metrics.contexts.PowerConsumption)
        check_monitoring("BMC", MonitoringContextKeys.PowerConsumption, self.metrics.contexts.PowerConsumption)

        self.vendor.get_bmc().read_oob_power_consumption(self.metrics.contexts.PowerConsumption)
        check_monitoring("BMC", MonitoringContextKeys.PowerConsumption, self.metrics.contexts.PowerConsumption)

        self.vendor.get_bmc().read_power_supplies(self.metrics.contexts.PowerSupplies)
        check_monitoring("BMC", MonitoringContextKeys.PowerSupplies, self.metrics.contexts.PowerSupplies)

        # - checking if pdu monitoring works
        if pdus:
            for pdu in pdus:
                pdu.read_power_consumption(self.metrics.contexts.PowerConsumption)
            check_monitoring("PDU", MonitoringContextKeys.PowerConsumption, self.metrics.contexts.PowerConsumption)

    def preup(self, precision_s: int):
        """Start turbostat monitoring before a benchmark run.

        This should be called before each benchmark to initialize turbostat
        in background mode. Turbostat will be triggered on-demand via EOL.

        Args:
            precision_s: Sampling interval in seconds (used for timeouts only)
        """
        self.__reset_metrics()
        if self.turbostat:
            # Reinitialize turbostat metrics after reset (fast, doesn't run turbostat)
            self.turbostat.reinitialize_metrics()
            print("Monitoring/turbostat: starting background monitoring with EOL-triggered sampling")
            self.turbostat.start_background()

    def predown(self):
        """Stop turbostat monitoring after a benchmark run.

        This should be called after each benchmark to cleanly shutdown
        the background turbostat process.
        """
        if self.turbostat:
            print("Monitoring/turbostat: stopping background monitoring")
            self.turbostat.stop_background()

    def __monitor_bmc(self):
        """Monitor the bmc metrics"""
        self.vendor.get_bmc().read_thermals(self.metrics.contexts.Thermal)
        self.vendor.get_bmc().read_fans(self.metrics.contexts.Fans)
        self.vendor.get_bmc().read_power_consumption(self.metrics.contexts.PowerConsumption)
        self.vendor.get_bmc().read_oob_power_consumption(self.metrics.contexts.PowerConsumption)
        self.vendor.get_bmc().read_power_supplies(self.metrics.contexts.PowerSupplies)

    def __monitor_pdus(self):
        """Monitor the PDU metrics"""
        for pdu in self.vendor.get_pdus():
            pdu.read_power_consumption(self.metrics.contexts.PowerConsumption)

    def __compact(self):
        """Compute statistics"""
        # Compact all metrics in contexts
        self.metrics.contexts.compact_all()

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
        self.metrics.contexts.Monitor.BMC = {"Polling": MonitorMetric("Polling", "ms")}
        self.metrics.contexts.Monitor.PDU = {"Polling": MonitorMetric("Polling", "ms")}
        self.metrics.contexts.Monitor.CPU = {"Polling": MonitorMetric("Polling", "ms")}

        # When will we hit "duration_s" ?
        end_of_run_ns = start_monitoring_ns + (duration_s * 1e9)
        loops_done = 0
        compact_count = 0

        def next_iter_ns() -> float:
            # When does the next iteration must starts ?
            return start_monitoring_ns + ((loops_done + 1) * precision_s) * 1e9

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

            start_bmc_ns = time.monotonic_ns()
            self.__monitor_bmc()
            # Let's monitor the time spent at monitoring the BMC, in milliseconds
            self.metrics.contexts.Monitor.BMC["Polling"].add((time.monotonic_ns() - start_bmc_ns) * 1e-6)

            if self.vendor.get_pdus():
                start_pdu_ns = time.monotonic_ns()
                self.__monitor_pdus()
                # Let's monitor the time spent at monitoring the PDUs, in milliseconds
                self.metrics.contexts.Monitor.PDU["Polling"].add((time.monotonic_ns() - start_pdu_ns) * 1e-6)

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
