import json
import pathlib
from statistics import mean
from typing import Any  # noqa: F401
from common import fatal

EVENTS = "events"
MIN = "min"
MAX = "max"
MEAN = "mean"


class Bench:
    def __init__(self, trace, bench_name: str):
        self.trace = trace
        self.bench = self.trace.get_trace()["bench"][bench_name]
        self.bench_name = bench_name

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

    def __get_events(self, metric_name: str, serie: str) -> list:
        """Return the "serie" values of metric_name"""
        return self.get_monitoring_metric(metric_name)[serie].get(EVENTS)

    def get_min_events(self, metric_name: str) -> list:
        """Return the min values of metric_name"""
        return self.__get_events(metric_name, MIN)

    def get_mean_events(self, metric_name: str) -> list:
        """Return the mean values of metric_name"""
        return self.__get_events(metric_name, MEAN)

    def get_max_events(self, metric_name: str) -> list:
        """Return the max values of metric_name"""
        return self.__get_events(metric_name, MAX)

    def get_monitoring(self) -> dict:
        """Return the monitoring metrics."""
        return self.get("monitoring")

    def get_monitoring_metric(self, metric_name) -> dict:
        """Return one monitoring metric."""
        return self.get_monitoring()[metric_name]

    def get_monitoring_metric_unit(self, metric_name) -> str:
        """Return one monitoring metric unit"""
        return self.get_monitoring_metric(metric_name)["min"]["unit"]

    def get_monitoring_metric_axis(self, metric_name) -> tuple[Any, Any, Any]:
        """Return adjusted metric axis values"""
        unit = self.get_monitoring_metric_unit(metric_name)
        # return y_max, y_major_tick, y_minor_tick
        if unit == "Percent":
            return 100, 10, 5
        elif unit == "RPM":
            return 21000, 1000, 250
        elif unit == "Celsius":
            return 110, 10, 5
        return None, None, None

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
        title = (
            f"System: {d['serial']} {d['product']} Bios "
            f"v{d['bios']['version']} Linux Kernel {k['release']}"
        )
        title += (
            f"\nProcessor: {c['model']} with {c['physical_cores']} cores "
            f"and {c['numa_domains']} NUMA domains"
        )
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
            fatal(f"Unsupported {em} engine")
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
        self, perf="", traces_perf=None, perf_watt=None, watt=None, index=None
    ) -> None:
        """Extract performance and power efficiency"""
        try:
            if perf and traces_perf is not None:
                # Extracting performance
                value = self.get(perf)
                # but let's consider sum_speed for memrate runs
                if self.engine_module() in ["memrate"]:
                    value = self.get(perf)["sum_speed"]
                if index is None:
                    traces_perf.append(value)
                else:
                    traces_perf[index] = value

            # If we want to keep the perf/watt ratio, let's compute it
            if perf_watt is not None:
                metric = value / self.get_trace().get_metric_mean(self)
                if index is None:
                    perf_watt.append(metric)
                else:
                    perf_watt[index] = metric

            # If we want to keep the power consumption, let's save it
            if watt is not None:
                metric = self.get_trace().get_metric_mean(self)
                if index is None:
                    watt.append(metric)
                else:
                    watt[index] = metric
        except ValueError:
            fatal(f"No {perf} found in {self.get_bench_name()}")

    def get_components(self, component_name):
        """Return the list of components of a benchmark."""
        return [
            key
            for key, _ in self.get_monitoring().items()
            if component_name in key.lower()
        ]

    def get_components_by_unit(self, unit):
        """Return the list of components with a specific unit."""
        return [
            key
            for key, value in self.get_monitoring().items()
            if unit in value["min"]["unit"].lower()
        ]

    def get_samples_count(self, metric_name: str):
        """Return the number of monitoring samples for a given metric"""
        return len(self.get_mean_events(metric_name))

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
    def __init__(self, filename, logical_name, metric_name):
        self.filename = filename
        self.logical_name = logical_name
        self.metric_name = metric_name
        self.__validate__()

    def get_name(self) -> str:
        return self.logical_name

    def __validate__(self) -> None:
        """Validate the new trace file"""
        if not pathlib.Path(self.filename).is_file():
            raise ValueError(f"{self.filename} is not a valid file")

        # Can we load the input file as a valid json ?
        try:
            self.trace = json.loads(pathlib.Path(self.filename).read_bytes())
        except ValueError:
            raise ValueError(f"{self.filename} is not a valid JSON file")

        # If no logical name was given, let's use the serial number as a default
        if not self.logical_name:
            self.logical_name = self.get_chassis_serial()
        elif self.logical_name == "CPU":
            # keyword CPU can be used to automatically use the CPU model as logical name
            self.logical_name = ""
            if self.get_sockets_count() > 1:
                self.logical_name = f"{self.get_sockets_count()} x "
            self.logical_name += self.get_sanitized_cpu_model()

        # Let's check if the monitoring metrics exists in the first job
        try:
            isinstance(self.get_metric_mean(self.first_bench()), float)
        except KeyError:
            fatal(
                f"Cannot find monitoring metric '{self.metric_name}' in {self.filename}"
            )

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
            self.get_cpu()["model"]
            .split("@", 1)[0]
            .replace("(R)", "")
            .replace("Processor", "")
            .replace("CPU", "")
        )

    def get_sockets_count(self):
        return self.get_cpu()["sockets"]

    def get_physical_cores(self):
        return self.get_cpu()["physical_cores"]

    def get_kernel(self):
        return self.get_environment().get("kernel")

    def get_enclosure_serial(self):
        return self.get_dmi()["chassis"]["serial"]

    def get_enclosure_product(self):
        return self.get_dmi()["chassis"]["product"]

    def get_chassis_serial(self):
        return self.get_dmi()["serial"]

    def get_chassis_product(self):
        return self.get_dmi()["product"]

    def get_metric_name(self) -> str:
        """Return the metric name"""
        return self.metric_name

    def get_metric_mean_by_name(self, bench_name: str, metric_name="") -> float:
        """Return the mean of chosen metric"""
        return self.get_metric_mean(self.bench(bench_name), metric_name)

    def get_metric_mean(self, bench: Bench, metric_name="") -> float:
        """Return the mean of chosen metric"""
        if not metric_name:
            metric_name = self.metric_name
        return mean(bench.get_mean_events(metric_name))

    def bench_list(self) -> dict:
        """Return the list of benches"""
        return self.get_trace()["bench"]

    def first_bench(self) -> Bench:
        """Return the first bench"""
        return self.bench(next(iter(sorted(self.bench_list()))))

    def bench(self, bench_name: str) -> Bench:
        """Return one bench"""
        return Bench(self, bench_name)

    def get_benches_by_job(self, job: str) -> list[Bench]:
        """Return the list of benches linked to job 'job'"""
        # We only keep keep jobs liked to the searched job
        return [
            self.bench(bench_name)
            for bench_name in self.bench_list()
            if self.bench(bench_name).job_name() == job
        ]

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
