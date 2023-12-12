import time
from typing import Any
from threading import Thread
from ..environment.hardware import BaseHardware
from ..utils import helpers as h
from .monitoring_structs import Metrics, MonitorMetric


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
        self.__reset_metrics()
        self.prepare()

    def get_monotonic_clock(self):
        """Return the raw clock time, not sensible of ntp adjustments."""
        return time.monotonic_ns()

    def __get_metrics(self):
        """Return the actual metrics."""
        return self.metrics

    def __get_metric(self, metric: Metrics):
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

        def check_monitoring(func, type: str):
            metrics = func
            if not len(metrics):
                h.fatal(f"Cannot detect {type} metrics from BMC")

            print(
                f"Monitoring {type} metrics:"
                + ", ".join(
                    [
                        f"{len(metrics[pc])}x{pc}"
                        for pc in metrics
                        if len(metrics[pc]) > 0
                    ]
                )
            )

        # - checking the bmc monitoring works
        # These calls will also initialize the datastructures out of the monitoring loop
        check_monitoring(
            self.vendor.get_bmc().read_thermals(self.__get_metric(Metrics.THERMAL)),
            "thermal",
        )
        check_monitoring(
            self.vendor.get_bmc().read_fans(self.__get_metric(Metrics.FANS)), "fans"
        )
        check_monitoring(
            self.vendor.get_bmc().read_power_consumption(
                self.__get_metric(Metrics.POWER_CONSUMPTION)
            ),
            "power",
        )
        check_monitoring(
            self.vendor.get_bmc().read_power_supplies(
                self.__get_metric(Metrics.POWER_SUPPLIES)
            ),
            "power_supplies",
        )

    def __monitor_bmc(self):
        """Monitor the bmc metrics"""
        self.vendor.get_bmc().read_thermals(self.__get_metric(Metrics.THERMAL))
        self.vendor.get_bmc().read_fans(self.__get_metric(Metrics.FANS))
        self.vendor.get_bmc().read_power_consumption(
            self.__get_metric(Metrics.POWER_CONSUMPTION)
        )
        self.vendor.get_bmc().read_power_supplies(
            self.__get_metric(Metrics.POWER_SUPPLIES)
        )

    def __compact(self):
        """Compute statistics"""
        for metric_name, metric_type in self.metrics.items():
            # Do not compact metadata
            if metric_name in [
                "precision",
                "frequency",
                "iteration_time",
                "monitoring_time",
                "overdue_time_ms",
            ]:
                continue
            for _, component in metric_type.items():
                for _, metric in component.items():
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
        self.metrics["precision"] = precision
        self.metrics["frequency"] = frequency
        self.metrics["iteration_time"] = frequency * precision
        self.metrics[str(Metrics.MONITOR)] = {
            "BMC": {"Polling": MonitorMetric("Polling", "ms")}
        }
        # When will we hit "duration" ?
        end_of_run = start_run + duration * 1e9
        loops_done = 0

        def next_iter():
            # When does the next iteration must starts ?
            return start_run + ((loops_done + 1) * precision) * 1e9

        while True:
            if loops_done and loops_done % frequency == 0:
                # At every frequency, the maths are computed
                self.__compact()
            start = self.get_monotonic_clock()
            self.__monitor_bmc()
            end = self.get_monotonic_clock()
            monitoring_duration = end - start
            # Let's monitor the time spent at monitoring the BMC
            self.__get_metric(Metrics.MONITOR)["BMC"]["Polling"].add(
                monitoring_duration * 1e-6
            )

            # Based on the time passed, let's compute the amount of sleep time
            # to keep in sync with the expected precision
            sleep_time_ns = next_iter() - self.get_monotonic_clock()  # stime
            sleep_time = sleep_time_ns / 1e9

            # If the the current time + sleep_time is above the total duration (we accept up to 500ms overdue)
            if (end + monitoring_duration + sleep_time_ns) > (end_of_run + 0.5 * 1e9):
                # We can stop the monitoring, no more measures will be done
                break

            time.sleep(sleep_time)
            loops_done = loops_done + 1

        # Monitoring is over, let's compute the maths
        self.__compact()

        # How much time did we spent in this loop ?
        completed_time = self.get_monotonic_clock()
        self.metrics["monitoring_time"] = (completed_time - start_run) * 1e-9

        # We were supposed to last "duration", how close are we from this metric ?
        self.metrics["overdue_time_ms"] = (
            (completed_time - start_run) - (duration * 1e9)
        ) * 1e-6

        # And return the final metrics
        return self.__get_metrics()

    def __reset_metrics(self):
        self.metrics = {}
        self.__set_metric(Metrics.FANS, {})
        self.__set_metric(Metrics.POWER_CONSUMPTION, {})
        self.__set_metric(Metrics.POWER_SUPPLIES, {})
        self.__set_metric(Metrics.THERMAL, {})
        self.__set_metric(Metrics.MONITOR, {})
