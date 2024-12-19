import json
import pathlib
from statistics import mean
from typing import Any  # noqa: F401
from graph.common import fatal
from hwbench.bench.monitoring_structs import (
    Metrics,
    MonitoringMetadata,
    MonitorMetric,
    Power,
    PowerContext,
    Temperature,
)

EVENTS = "events"
MIN = "min"
MAX = "max"
MEAN = "mean"


class Bench:
    def __init__(self, trace, bench_name: str):
        self.trace = trace
        self.bench = self.trace.get_trace()["bench"][bench_name]
        self.bench_name = bench_name
        self.metrics: Any = {}

    def get_bench_name(self) -> str:
        """Return the benchmark name"""
        return self.bench_name

    def settings(self) -> dict:
        """Return all settings of the current benchmark"""
        return self.bench

    def get(self, setting):
        """Return a specific setting."""
        return self.bench.get(setting)

    def skipped(self) -> bool:
        skipped = self.get("skipped")
        if not skipped:
            return False
        return skipped

    def cpu_pin(self) -> list:
        """Return the list of pinned cpu."""
        cpu_pin = self.get("cpu_pin")
        if isinstance(cpu_pin, int):
            cpu_pin = [cpu_pin]
        return cpu_pin

    def get_title_engine_name(self) -> str:
        """Do not repeat engine, engine_module and parameter if identical."""
        title = f"{self.engine()} "
        if self.engine_module() != self.engine():
            title += f"{self.engine_module()} "
        if self.engine_module_parameter() != self.engine_module():
            title += f"{self.engine_module_parameter()} "
        return title

    def get_monitoring(self) -> dict:
        """Return the monitoring metrics."""
        return self.get("monitoring")

    def load_monitoring(self):
        self.metrics = {}
        m = self.get_monitoring()
        if m:
            for metric in m.keys():
                if metric in MonitoringMetadata.list_str():
                    self.metrics[metric] = m[metric]
                elif metric in Metrics.list_str():
                    self.metrics[metric] = {}
                    for component_family in m[metric].keys():
                        self.metrics[metric][component_family] = {}
                        for measure in m[metric][component_family]:
                            original_measure = m[metric][component_family][measure]
                            if original_measure["unit"] == "Watts":
                                mm = Power(measure, original_measure["unit"])
                            elif original_measure["unit"] == "Celsius":
                                mm = Temperature(measure, original_measure["unit"])
                            else:
                                mm = MonitorMetric(measure, original_measure["unit"])
                            mm.load_from_dict(original_measure, measure)
                            self.metrics[metric][component_family][measure] = mm
                else:
                    fatal(f"Unexpected {metric} in monitoring")
        return self.metrics

    def get_monitoring_metric(self, metric: Metrics) -> dict[str, dict[str, MonitorMetric]]:
        """Return one monitoring metric."""
        return self.metrics[str(metric)]

    def get_monitoring_metric_by_name(self, metric: Metrics, metric_name: str) -> MonitorMetric:
        """Return one monitoring metric."""
        component, measure = metric_name.split(".")
        return self.metrics[str(metric)][component][measure]

    def get_monitoring_metric_axis(self, unit: str) -> tuple[Any, Any, Any]:
        """Return adjusted metric axis values"""
        # return y_max, y_major_tick, y_minor_tick
        if unit == "Percent":
            return 100, 10, 5
        elif unit == "RPM":
            return 21000, 1000, 250
        elif unit == "Celsius":
            return 110, 10, 5
        return None, None, None

    def get_component(self, metric_type: Metrics, component: Any) -> dict[str, MonitorMetric]:
        return self.get_monitoring_metric(metric_type)[str(component)]

    def get_single_metric(self, metric_type: Metrics, component: Any, metric: Any) -> MonitorMetric:
        return self.get_component(metric_type, component)[str(metric)]

    def get_samples_count(self):
        """Return the number of monitoring samples"""
        return self.metrics[str(MonitoringMetadata.SAMPLES_COUNT)]

    def get_first_metric(self, metric_type: Metrics):
        """Return the first metric of a given metric type"""
        metric = self.get_monitoring_metric(metric_type)
        component = metric[next(iter(metric))]
        return component[next(iter(component))]

    def get_metric_unit(self, metric_type: Metrics):
        """Return the metric unit of a given metric"""
        return self.get_first_metric(metric_type).get_unit()

    def get_all_metrics(self, metric_type: Metrics, filter=None) -> list[MonitorMetric]:
        """Return all metrics of a given type."""
        metrics = []
        for _, metric in self.get_monitoring_metric(metric_type).items():
            for component_name, component in metric.items():
                if not filter:
                    metrics.append(component)
                else:
                    if filter in component_name:
                        metrics.append(component)
        return metrics

    def title(self) -> str:
        """Prepare the benchmark title name."""
        title = f"Stressor: {self.workers()} x {self.engine()} "
        title += f"{self.engine_module()} "
        title += f"{self.engine_module_parameter()} for {self.duration()} seconds"
        return title

    def get_system_title(self):
        """Prepare the graph system title."""
        d = self.get_trace().get_dmi()
        c = self.get_trace().get_cpu()
        k = self.get_trace().get_kernel()
        title = f"System: {d['serial']} {d['product']} Bios " f"v{d['bios']['version']} Linux Kernel {k['release']}"
        title += f"\nProcessor: {c['model']} with {c['physical_cores']} cores " f"and {c['numa_domains']} NUMA domains"
        return title

    def job_name(self) -> str:
        """Return the job_name associated to this bench."""
        return self.get("job_name")

    def engine(self) -> str:
        """Return the engine name."""
        return self.get("engine")

    def engine_module(self) -> str:
        """Return the engine module name."""
        return self.get("engine_module")

    def engine_module_parameter(self) -> str:
        """Return the engine module parameter name."""
        return self.get("engine_module_parameter")

    def duration(self) -> float:
        """Return the duration of the benchmark."""
        return self.get("timeout")

    def workers(self) -> int:
        """Return the number of workers."""
        return self.get("workers")

    def prepare_perf_metrics(self) -> tuple[list, str]:
        """Preparing a list of metrics and units based on the executed benchmark"""
        perf_list = []
        unit = ""
        em = self.engine_module()
        # Preparing the performance metric to graph
        if self.engine() not in ["stressng", "sleep"]:
            fatal(f"Unsupported {self.engine()} engine")
        if self.engine() == "stressng":
            if em in ["cpu", "qsort", "vnni"]:
                perf_list = ["bogo ops/s"]
                unit = "Bogo op/s"
            elif em in ["memrate"]:
                for size in [8, 16, 32, 64, 128, 256, 512, 1024]:
                    perf_list.append(f"write{size}")
                    perf_list.append(f"read{size}")
                unit = "MB/s"
            elif em in ["stream"]:
                perf_list = ["sum_total", "sum_write", "sum_read"]
                unit = "MB/s"
            else:
                fatal(f"Unsupported {em} engine module")
        elif self.engine() == "sleep":
            perf_list = ["bogo ops/s"]
            unit = "Bogo op/s"
        return perf_list, unit

    def get_trace(self):
        """Return the Trace object associated to this benchmark"""
        return self.trace

    def add_perf(
        self,
        perf="",
        traces_perf=None,
        perf_watt=None,
        watt=None,
        watt_err=None,
        cpu_clock=None,
        cpu_clock_err=None,
        index=None,
    ) -> None:
        """Extract performance and power efficiency"""
        try:
            if perf and traces_perf is not None:
                try:
                    # Extracting performance
                    metric_name = perf
                    value = self.get(perf)
                    # but let's consider sum_speed for memrate runs
                    if self.engine_module() in ["memrate"]:
                        metric_name = f"{perf}/sum_speed"
                        value = self.get(perf)["sum_speed"]
                    try:
                        effective_runtime = self.get("effective_runtime")
                        delta = abs(effective_runtime - self.duration())
                        # The effective runtime must be within ~1sec compared to the expected duration
                        if delta > 1:
                            print(
                                f"{self.trace.get_name()}/{self.get_bench_name()} didn't completed on time. "
                                f"Effective_runtime={effective_runtime} vs {self.duration()} : delta=[{delta:.2f}s; {delta/self.duration()*100:.2f}%]"
                            )
                    except TypeError:
                        # We can ignore the delay computation if effective_runtime is not defined
                        # Not all engines are able to provide an effective_runtime.
                        pass
                    if index is None:
                        traces_perf.append(value)
                    else:
                        traces_perf[index] = value
                except TypeError:
                    fatal(f"{self.trace.get_name()}/{self.get_bench_name()}: unable to find metric {metric_name}")

            # If we want to keep the perf/watt ratio, let's compute it
            if perf_watt is not None:
                metric = value / mean(
                    self.get_monitoring_metric_by_name(
                        Metrics.POWER_CONSUMPTION, self.get_trace().get_metric_name()
                    ).get_mean()
                )
                if index is None:
                    perf_watt.append(metric)
                else:
                    perf_watt[index] = metric

            # If we want to keep the power consumption, let's save it
            if watt is not None:
                metric = mean(
                    self.get_monitoring_metric_by_name(
                        Metrics.POWER_CONSUMPTION, self.get_trace().get_metric_name()
                    ).get_mean()
                )
                if index is None:
                    watt.append(metric)
                else:
                    watt[index] = metric

                # If we want to keep the error distribution to plot error bars
                if watt_err is not None:
                    mean_value = mean(
                        self.get_monitoring_metric_by_name(
                            Metrics.POWER_CONSUMPTION,
                            self.get_trace().get_metric_name(),
                        ).get_mean()
                    )
                    min_value = mean(
                        self.get_monitoring_metric_by_name(
                            Metrics.POWER_CONSUMPTION,
                            self.get_trace().get_metric_name(),
                        ).get_min()
                    )
                    max_value = mean(
                        self.get_monitoring_metric_by_name(
                            Metrics.POWER_CONSUMPTION,
                            self.get_trace().get_metric_name(),
                        ).get_max()
                    )
                    metric = (mean_value - min_value, max_value - mean_value)
                    if index is None:
                        watt_err.append(metric)
                    else:
                        watt_err[index] = metric

            if cpu_clock is not None:
                mm = self.get_monitoring_metric(Metrics.FREQ)
                mean_values = []
                min_values = []
                max_values = []

                for freq_metric in mm:
                    if freq_metric != "CPU":
                        continue
                    # We have to compute metrics of all systems cores
                    for core in mm[freq_metric]:
                        # MIN of min ?
                        # Mean of mean ?
                        # Max of max ?
                        min_values.append(min(mm[freq_metric][core].get_min()))
                        mean_values.append(mean(mm[freq_metric][core].get_mean()))
                        max_values.append(max(mm[freq_metric][core].get_max()))
                    min_value = min(min_values)
                    mean_value = mean(mean_values)
                    max_value = max(max_values)

                if index is None:
                    cpu_clock.append(mean_value)
                else:
                    cpu_clock[index] = mean_value

                # If we want to keep the error distribution to plot error bars
                if cpu_clock_err is not None:
                    metric = (mean_value - min_value, max_value - mean_value)
                    if index is None:
                        cpu_clock_err.append(metric)
                    else:
                        cpu_clock_err[index] = metric

        except ValueError:
            fatal(f"No {perf} found in {self.get_bench_name()}")

    def get_time_interval(self):
        return self.metrics[str(MonitoringMetadata.ITERATION_TIME)]

    def get_psu_power(self):
        psus = self.get_component(Metrics.POWER_SUPPLIES, PowerContext.BMC)
        power = 0
        if psus:
            power = [0] * len(psus[next(iter(psus))].get_samples())
            for _, psu in psus.items():
                count = 0
                for value in psu.get_mean():
                    power[count] = power[count] + value
                    count = count + 1
        return power

    def differences(self, other):
        """Compare if two Bench objects are similar"""
        for setting in self.settings():
            # We just want to ensure jobs are similar in their design
            # The skip_list is matching items that may vary accross systems / runs
            skip_list = [
                "bogo",
                "monitoring",
                "cpu_pin",
                "detail",
                "avg_",
                "sum_",
                "memset",
            ]

            # Skiping network results
            for size in [8, 16, 32, 64, 128, 256, 512, 1024]:
                skip_list.append(f"write{size}")
                skip_list.append(f"read{size}")

            if any([skip in setting for skip in skip_list]):
                continue

            if self.get(setting) != other.get(setting):
                msg = f"Setting {self.get_bench_name()}/{setting} does not match between {self.get_trace().get_filename()} and {other.get_trace().get_filename()}"
                msg += f"\n{self.get_trace().get_filename()}: {self.get_bench_name()}/{setting} = {self.get(setting)}"
                msg += f"\n{self.get_trace().get_filename()}: {self.get_bench_name()}/{setting} = {other.get(setting)}"
                return msg

        return ""


class Trace:
    def __init__(
        self,
        filename: str = "",
        logical_name: str = "",
        metric_name: str = "",
    ):
        self.filename = filename
        self.logical_name = logical_name
        self.metric_name = metric_name
        self.__load_file()

    def get_name(self) -> str:
        return self.logical_name

    def __load_file(self):
        """Validate the new trace file"""
        if not pathlib.Path(self.filename).is_file():
            raise ValueError(f"{self.filename} is not a valid file")

        # Can we load the input file as a valid json ?
        try:
            self.trace = json.loads(pathlib.Path(self.filename).read_bytes())
        except ValueError:
            raise ValueError(f"{self.filename} is not a valid JSON file")

    def validate(self) -> None:
        # If no logical name was given, let's use the serial number as a default
        if not self.logical_name:
            self.logical_name = self.get_server_serial()
        elif self.logical_name == "CPU":
            # keyword CPU can be used to automatically use the CPU model as logical name
            self.logical_name = ""
            if self.get_sockets_count() > 1:
                self.logical_name = f"{self.get_sockets_count()} x "
            self.logical_name += self.get_sanitized_cpu_model()

        # Let's check if the monitoring metrics exists in the first job
        first_bench = self.first_bench()
        metrics = first_bench.load_monitoring()
        if not metrics:
            fatal(f"{self.filename}: Cannot find monitoring metrics")

        if str(Metrics.POWER_CONSUMPTION) not in metrics:
            fatal(f"{self.filename}: Cannot find power consumption metrics")

        try:
            first_bench.get_monitoring_metric_by_name(Metrics.POWER_CONSUMPTION, self.metric_name)
        except (KeyError, ValueError):
            try:
                metrics = " ".join(self._list_power_metrics())
            except BaseException as e:
                metrics = f"none detected: {e}"
            fatal(
                f"{self.filename}: Cannot find {self.metric_name} in power consumption metrics.\
                        \nUse the list toplevel subcommand to detect possible values: {metrics}"
            )

    def _list_power_metrics(self) -> list[str]:
        first_bench = self.first_bench()
        first_bench.load_monitoring()
        power_metrics = []
        for name, value in first_bench.get_monitoring_metric(Metrics.POWER_CONSUMPTION).items():
            for v in value:
                power_metrics.append(f"{name}.{v}")
        return power_metrics

    def list_power_metrics(self):
        print("List of power metrics:")
        for metric in self._list_power_metrics():
            print(metric)

    def get_filename(self) -> str:
        """Return the filename associated to this Trace object."""
        return self.filename

    def get_trace(self) -> dict:
        """Return the trace dict"""
        return self.trace

    def get_hardware(self) -> dict:
        return self.trace["hardware"]

    def get_original_config(self) -> dict:
        return self.trace["config"]

    def get_environment(self) -> dict:
        return self.trace["environment"]

    def get_dmi(self):
        return self.get_hardware().get("dmi")

    def get_cpu(self):
        return self.get_hardware().get("cpu")

    def get_sanitized_cpu_model(self):
        return (
            self.get_cpu()["model"].split("@", 1)[0].replace("(R)", "").replace("Processor", "").replace("CPU", "")
        ).strip()

    def get_sockets_count(self):
        return self.get_cpu()["sockets"]

    def get_physical_cores(self):
        return self.get_cpu()["physical_cores"]

    def get_kernel(self):
        return self.get_environment().get("kernel")

    def get_chassis_serial(self):
        return self.get_dmi()["chassis"]["serial"]

    def get_chassis_product(self):
        return self.get_dmi()["chassis"]["product"]

    def get_server_serial(self):
        return self.get_dmi()["serial"]

    def get_server_product(self):
        return self.get_dmi()["product"]

    def get_metric_name(self) -> str:
        """Return the metric name"""
        return self.metric_name

    def bench_list(self) -> dict:
        """Return the list of benches"""
        return self.get_trace()["bench"]

    def first_bench(self) -> Bench:
        """Return the first bench"""
        b = self.bench(next(iter(sorted(self.bench_list()))))
        b.load_monitoring()
        return b

    def bench(self, bench_name: str) -> Bench:
        """Return one bench"""
        b = Bench(self, bench_name)
        b.load_monitoring()
        return b

    def get_benches_by_job(self, job: str) -> list[Bench]:
        """Return the list of benches linked to job 'job'"""
        # We only keep keep jobs liked to the searched job
        return [self.bench(bench_name) for bench_name in self.bench_list() if self.bench(bench_name).job_name() == job]

    def get_benches_by_job_per_emp(self, job: str) -> dict:
        """Return benches linked to job 'job' sorted by engine module parameter"""
        jobs = {}  # type: dict[str, dict[str, Any]]
        # For each bench associated to job 'job'
        for bench in self.get_benches_by_job(job):
            emp = bench.engine_module_parameter()
            # If we don't know this emp, let's create its datastructure
            if emp not in jobs:
                jobs[emp] = {}
                jobs[emp]["bench"] = []
                # We also link the performance metrics if we need to graph them
                jobs[emp]["metrics"] = bench.prepare_perf_metrics()

            # The Bench object is directly linked to ease future parsing
            jobs[emp]["bench"].append(bench)
        return jobs
