import time
from typing import Any
from threading import Thread
from ..environment.hardware import BaseHardware
from ..environment.turbostat import Turbostat
from ..utils import helpers as h
from .monitoring_structs import Metrics, MonitorMetric, MonitoringMetadata


class ThreadWithReturnValue(Thread):
    """A thread class that return target's return value"""

    def __init__(
        self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None
    ):
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
        self.metrics: Any = {}
        self.executor: ThreadWithReturnValue
        self.turbostat: Turbostat = None  # type: ignore[assignment]
        self.__reset_metrics()
        self.prepare()

    def get_monotonic_clock(self):
        """Return the raw clock time, not sensible of ntp adjustments."""
        return time.monotonic_ns()

    def __get_metrics(self):
        """Return the actual metrics."""
        return self.metrics

    def get_metric(self, metric: Metrics):
        """Return one metric."""
        return self.metrics[str(metric)]

    def __set_metric(self, metric: Metrics, value: dict[str, dict[str, MonitorMetric]]):
        """Set one metric"""
        self.metrics[str(metric)] = value

    def prepare(self):
        """Preparing the monitoring"""
        # Let's be sure the monitoring is functional by
        # - checking the BMC is actually connected to the network
        if self.vendor.get_bmc().get_ip() == "0.0.0.0":
            h.fatal("BMC has no IP, monitoring will not be possible")
        print(
            f"Starting monitoring for {self.vendor.name()} vendor with {self.vendor.get_bmc().get_ip()}"
        )

        def check_monitoring(metric: Metrics):
            data = self.get_metric(metric)
            if not len(data):
                h.fatal(f"Cannot detect {str(metric)} metrics")

            print(
                f"Monitoring {str(metric)} metrics:"
                + ", ".join(
                    [f"{len(data[pc])}x{pc}" for pc in data if len(data[pc]) > 0]
                )
            )

        # - checking if the CPU monitoring works
        if self.hardware.cpu.get_arch() == "x86_64":
            self.turbostat = Turbostat(
                self.hardware,
                self.get_metric(Metrics.FREQ),
                self.get_metric(Metrics.POWER_CONSUMPTION),
            )
            check_monitoring(Metrics.FREQ)

        # - checking if the bmc monitoring works
        # These calls will also initialize the datastructures out of the monitoring loop
        self.vendor.get_bmc().read_thermals(self.get_metric(Metrics.THERMAL))
        check_monitoring(Metrics.THERMAL)

        self.vendor.get_bmc().read_fans(self.get_metric(Metrics.FANS))
        check_monitoring(Metrics.FANS)

        self.vendor.get_bmc().read_power_consumption(
            self.get_metric(Metrics.POWER_CONSUMPTION)
        )
        check_monitoring(Metrics.POWER_CONSUMPTION)

        self.vendor.get_bmc().read_power_supplies(
            self.get_metric(Metrics.POWER_SUPPLIES)
        )
        check_monitoring(Metrics.POWER_SUPPLIES)

    def __monitor_bmc(self):
        """Monitor the bmc metrics"""
        self.vendor.get_bmc().read_thermals(self.get_metric(Metrics.THERMAL))
        self.vendor.get_bmc().read_fans(self.get_metric(Metrics.FANS))
        self.vendor.get_bmc().read_power_consumption(
            self.get_metric(Metrics.POWER_CONSUMPTION)
        )
        self.vendor.get_bmc().read_power_supplies(
            self.get_metric(Metrics.POWER_SUPPLIES)
        )

    def __compact(self):
        """Compute statistics"""
        for metric_name, metric_type in self.metrics.items():
            # Do not compact metadata
            if metric_name in MonitoringMetadata.list_str():
                continue
            for _, component in metric_type.items():
                for metric_name, metric in component.items():
                    metric.compact()

    def monitor(self, precision: int, frequency: int, duration: int):
        """Method to trigger asynchronous monitoring"""
        self.executor = ThreadWithReturnValue(
            target=self.__monitor,
            args=(
                precision,
                frequency,
                duration,
            ),
        )
        self.executor.start()

    def get_monitor_metrics(self):
        """Returns the metrics from the latest monitoring."""
        return self.executor.join()

    def __monitor(self, precision: int, frequency: int, duration: int):
        """Private method to perform the monitoring."""
        # This function will be a thread of self.monitor()
        #
        #  >|            duration                     |<
        #  >|    precision       |<                   |
        # __|monitor_bmc()|______|monitor_bmc()|______|
        #   |            >|stime |<
        # If frequency == 2, every two <precision> run, maths are computed
        start_run = self.get_monotonic_clock()
        self.__reset_metrics()
        self.metrics[str(MonitoringMetadata.PRECISION)] = precision
        self.metrics[str(MonitoringMetadata.FREQUENCY)] = frequency
        self.metrics[str(MonitoringMetadata.ITERATION_TIME)] = frequency * precision
        self.metrics[str(Metrics.MONITOR)] = {
            "BMC": {"Polling": MonitorMetric("Polling", "ms")}
        }
        # When will we hit "duration" ?
        end_of_run = start_run + duration * 1e9
        loops_done = 0
        compact_count = 0

        def next_iter():
            # When does the next iteration must starts ?
            return start_run + ((loops_done + 1) * precision) * 1e9

        while True:
            if self.turbostat:
                # Turbostat will run for the whole duration of this loop
                # We just retract a 2/10th of second to ensure it will not overdue
                self.turbostat.run(interval=(precision - 0.2))
            if loops_done and loops_done % frequency == 0:
                # At every frequency, the maths are computed
                self.__compact()
                compact_count = compact_count + 1
            start = self.get_monotonic_clock()
            self.__monitor_bmc()
            end = self.get_monotonic_clock()
            monitoring_duration = end - start
            # Let's monitor the time spent at monitoring the BMC
            self.get_metric(Metrics.MONITOR)["BMC"]["Polling"].add(
                monitoring_duration * 1e-6
            )

            # Based on the time passed, let's compute the amount of sleep time
            # to keep in sync with the expected precision
            sleep_time_ns = next_iter() - self.get_monotonic_clock()  # stime
            sleep_time = sleep_time_ns / 1e9

            # If the the current time + sleep_time is above the total duration (we accept up to 500ms overdue)
            if (end + monitoring_duration + sleep_time_ns) > (end_of_run + 0.5 * 1e9):
                # We can stop the monitoring, no more measures will be done
                self.turbostat.parse()
                break

            if sleep_time < 0:
                print(
                    f"Sleep time is greater than expected : {sleep_time} vs {precision}"
                )
            else:
                time.sleep(sleep_time)
                # Turbostat should be already completed, let's parse the output
                self.turbostat.parse()
            loops_done = loops_done + 1

        # How much time did we spent in this loop ?
        completed_time = self.get_monotonic_clock()
        self.metrics[str(MonitoringMetadata.MONITORING_TIME)] = (
            completed_time - start_run
        ) * 1e-9

        # We were supposed to last "duration", how close are we from this metric ?
        self.metrics[str(MonitoringMetadata.OVERDUE_TIME_MS)] = (
            (completed_time - start_run) - (duration * 1e9)
        ) * 1e-6

        self.metrics[str(MonitoringMetadata.SAMPLES_COUNT)] = compact_count

        # And return the final metrics
        return self.__get_metrics()

    def __reset_metrics(self):
        self.metrics = {}
        self.__set_metric(Metrics.FANS, {})
        self.__set_metric(Metrics.POWER_CONSUMPTION, {})
        self.__set_metric(Metrics.POWER_SUPPLIES, {})
        self.__set_metric(Metrics.THERMAL, {})
        if self.turbostat:
            freq, power = self.turbostat.reset_metrics({})
            self.__set_metric(Metrics.FREQ, freq)
            self.__set_metric(Metrics.POWER_CONSUMPTION, power)
        else:
            self.__set_metric(Metrics.FREQ, {})
        self.__set_metric(Metrics.MONITOR, {})
