from __future__ import annotations

import dataclasses
import functools
import importlib
import json
import pathlib
import tarfile
from enum import StrEnum
from statistics import mean
from typing import Any, Callable

from graph.common import fatal
from hwbench.bench.engine import Resource
from hwbench.bench.monitoring_structs import (
    CORE_FAMILY,
    CPU_RAM,
    GPU_FAMILY,
    FreqContextKeys,
    IPCContextKeys,
    MonitoringContextKeys,
    MonitoringContexts,
    MonitoringMetadata,
    MonitoringMetadataKeys,
    MonitorMetric,
    Power,
    PowerConsumptionContextKeys,
    PowerSuppliesContextKeys,
    Temperature,
    gpu_component_name,
)
from hwbench.utils.archive import extract_results_from_archive
from hwbench.utils.helpers import cpu_list_to_range

EVENTS = "events"
MIN = "min"
MAX = "max"
MEAN = "mean"


@dataclasses.dataclass(frozen=True)
class ScalingUnit:
    """What one worker of a benchmark is, from the renderers point of view.

    item_name  : the component a per-component view is named after
    axis_label : the label of the scaling axis
    family     : the component family the scaling acts on
    subset     : the components a given benchmark used, None for all of them
    count      : how many units a trace offers, to normalize a performance by
    per_worker : the extra axis annotation, when one unit is not one worker
    """

    item_name: str
    axis_label: str
    family: str
    subset: Callable[[Bench], set | None]
    # Directory and note of the view restricted to the components a benchmark used
    subset_dir: str
    subset_note: str
    count: Callable[[Trace, int], int]
    per_worker: Callable[[float], str]


def logical_cores_per_worker(ratio: float) -> str:
    """Annotate the scaling axis with the cores a cpu worker got."""
    cores = "core" if ratio == 1 else "cores"
    return f"({int(ratio)} logical {cores} per worker)"


CPU_SCALING_UNIT = ScalingUnit(
    "core",
    "Workers",
    CORE_FAMILY,
    lambda bench: bench.pinned_core_names(),
    "pinned_cores",
    "View limited to the pinned cores of each scaling step",
    # A cpu worker is a thread, so the performance of a trace is normalized by
    # the cores it has, not by the workers a step ran.
    lambda trace, workers: trace.get_physical_cores(),
    logical_cores_per_worker,
)
GPU_SCALING_UNIT = ScalingUnit(
    "gpu",
    "GPUs",
    GPU_FAMILY,
    lambda bench: bench.gpu_names(),
    "used_gpus",
    "View limited to the GPUs used at each scaling step",
    # One worker is one accelerator, and how many a server holds is irrelevant:
    # what matters is how many the step loaded.
    lambda trace, workers: workers,
    # A worker that is not a cpu thread has no core ratio to report.
    lambda ratio: "",
)

# The properties of an accelerator worth showing next to its results, as
# all-smi names them in its vendor details.
GPU_PROPERTIES = {
    "Driver": "Driver Version",
    "CUDA": "CUDA Version",
    "VBIOS": "vbios_version",
    "ECC": "ecc_mode_current",
}


def gpu_description(gpus: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Describe the accelerators of a trace, as (label, text) lines.

    The first line holds what every accelerator shares, like
    ('GPU', '8x NVIDIA B200, Driver: 610.57.04, CUDA: 13.3, ECC: enabled'). A
    property differing between them, like a VBIOS, gets one more line per value
    naming the GPUs having it: ('GPU 0-3', 'VBIOS: 97.00.FA.00.02').
    """
    if not gpus:
        return []
    properties = {}
    for index, gpu in gpus.items():
        detail = gpu.get("detail") or {}
        properties[int(index)] = {"model": gpu.get("name")} | {
            # Traces collected before the quotes were stripped by hwbench keep them
            label: str(detail[key]).strip('"')
            for label, key in GPU_PROPERTIES.items()
            if detail.get(key)
        }
    labels = ["model", *GPU_PROPERTIES]
    shared = {label for label in labels if len({str(props.get(label)) for props in properties.values()}) == 1}

    def describe(values: dict[str, Any]) -> list[str]:
        """Return the model as is, the other properties with their label."""
        return [
            str(value) if label == "model" else f"{label}: {value.lower() if label == 'ECC' else value}"
            for label, value in values.items()
            if value is not None
        ]

    first = next(iter(properties.values()))
    # The models differ when they are not shared: they are then given per group
    head = f"{len(properties)}x {first['model']}" if "model" in shared else f"{len(properties)} GPUs"
    common = describe({label: first.get(label) for label in GPU_PROPERTIES if label in shared})
    lines = [("GPU", ", ".join([head, *common]))]
    groups: dict[tuple, list[int]] = {}
    for position, props in sorted(properties.items()):
        groups.setdefault(tuple(props.get(label) for label in labels if label not in shared), []).append(position)
    if len(groups) > 1:
        varying = [label for label in labels if label not in shared]
        for values, indexes in groups.items():
            lines.append((f"GPU {cpu_list_to_range(indexes)}", ", ".join(describe(dict(zip(varying, values))))))
    return lines


@functools.cache
def engine_resources(engine: str) -> tuple[Resource, ...]:
    """Return the kinds of component an engine loads, as hwbench declares them."""
    try:
        return importlib.import_module(f"hwbench.engines.{engine}").Engine.resources
    except ModuleNotFoundError:
        return ()


def stressng_perf_metrics(bench: Bench) -> tuple[list, str]:
    """The stress-ng performance metric, which depends on the engine module."""
    em = bench.engine_module()
    if em in ["cpu", "qsort", "vnni"]:
        return ["bogo ops/s"], "Bogo op/s"
    if em in ["memrate"]:
        perf_list = []
        for size in [8, 16, 32, 64, 128, 256, 512, 1024]:
            perf_list.append(f"write{size}")
            perf_list.append(f"read{size}")
        return perf_list, "MB/s"
    if em in ["stream"]:
        return ["sum_total", "sum_write", "sum_read"], "MB/s"
    fatal(f"Unsupported {em} engine module")


def pantheon_perf_metrics(bench: Bench) -> tuple[list, str]:
    """The pantheon performance metric: the sum over the loaded accelerators.

    It scales with the number of GPUs of each step. The unit comes from the run:
    the pantheon workloads do not all measure the same thing, the compute ones
    report TFLOPS and the memory ones GB/s.
    """
    return ["score"], bench.get("score_unit") or "Score"


# What performance metric an engine reports, and in which unit. An engine whose
# metric depends on the run gets it from the bench rather than from a constant.
PERF_METRICS: dict[str, Callable[[Bench], tuple[list, str]]] = {
    "sleep": lambda bench: (["bogo ops/s"], "Bogo op/s"),
    "stressng": stressng_perf_metrics,
    "pantheon": pantheon_perf_metrics,
}

METRIC_AXIS = {
    "Percent": (110, 10, 5),
    "RPM": (21000, 1000, 250),
    "Celsius": (110, 10, 5),
}


class Event:
    def __init__(self, event_name: str, start_time: int, duration: int):
        self.event_name = event_name
        self.start_time = start_time
        self.duration = duration

    def get_name(self) -> str:
        return self.event_name

    def get_start_time(self) -> int:
        return self.start_time

    def get_duration(self) -> int:
        return self.duration

    def validate(self) -> None:
        if len(self.get_name()) == 0:
            fatal("Event: event_name is not defined")
        if self.get_start_time() < 0:
            fatal(f"Event {self.get_name}: start_time is lower than 0")
        if self.get_duration() <= 0:
            fatal(f"Event {self.get_name}: duration should be greater than 0")


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

    def get_monitoring(self) -> dict[str, Any]:
        """Return the monitoring metrics.
        The choice here is to replicate the old structure so that nothing breaks,
        especially since there is no typing/deserialization on this part yet.
        """
        legacy_monitoring = self.get("monitoring")
        new_monitoring = legacy_monitoring.get("contexts", None)
        if new_monitoring:
            return legacy_monitoring["metadata"] | new_monitoring
        else:
            return legacy_monitoring

    def load_monitoring(self):
        self.metrics = {}
        m = self.get_monitoring()
        meta_fields = list(field.name for field in dataclasses.fields(MonitoringMetadata))
        context_fields = list(field.name for field in dataclasses.fields(MonitoringContexts))
        if m:
            for metric in m:
                if metric in meta_fields:
                    self.metrics[metric] = m[metric]
                elif metric in context_fields:
                    self.metrics[metric] = {}
                    for component_family in m[metric]:
                        self.metrics[metric][component_family] = {}
                        for measure in m[metric][component_family]:
                            original_measure = m[metric][component_family][measure]
                            # Power and Temperature carry their unit in the class,
                            # their second argument is a first sample: passing the
                            # unit there would record it as a value.
                            if original_measure["unit"] == "Watts":
                                mm = Power(measure)
                            elif original_measure["unit"] == "Celsius":
                                mm = Temperature(measure)
                            else:
                                mm = MonitorMetric(measure, original_measure["unit"])
                            mm.load_from_dict(original_measure, measure)
                            self.metrics[metric][component_family][measure] = mm
                else:
                    fatal(f"Unexpected {metric} in monitoring")
        self.drop_incomplete_ram()
        return self.metrics

    def drop_incomplete_ram(self):
        """The memory power is optional: a benchmark missing some of its samples is silently
        graphed without it, instead of stopping every graph it would be drawn in."""
        cpu = self.metrics.get(MonitoringContextKeys.PowerConsumption, {}).get(PowerConsumptionContextKeys.CPU, {})
        samples_count = self.metrics.get(MonitoringMetadataKeys.samples_count)
        if CPU_RAM not in cpu or samples_count is None or len(cpu[CPU_RAM].get_mean()) >= samples_count:
            return
        del cpu[CPU_RAM]

    def get_monitoring_metric(self, metric: MonitoringContextKeys) -> dict[str, dict[str, MonitorMetric]]:
        """Return one monitoring metric."""
        return self.metrics[metric]

    def get_monitoring_metric_by_name(self, metric: MonitoringContextKeys, metric_name: str) -> MonitorMetric:
        """Return one monitoring metric."""
        component, measure = metric_name.split(".")
        return self.metrics[metric][component][measure]

    def get_monitoring_metric_axis(self, unit: str) -> tuple[Any, Any, Any]:
        """Return adjusted metric axis values"""
        return METRIC_AXIS.get(unit, (None, None, None))

    def get_component(self, metric_type: MonitoringContextKeys, component: Any) -> dict[str, MonitorMetric]:
        return self.get_monitoring_metric(metric_type)[str(component)]

    def get_single_metric(self, metric_type: MonitoringContextKeys, component: Any, metric: Any) -> MonitorMetric:
        return self.get_component(metric_type, component)[str(metric)]

    def get_samples_count(self):
        """Return the number of monitoring samples"""
        return self.metrics[MonitoringMetadataKeys.samples_count]

    def get_first_metric(self, metric_type: MonitoringContextKeys):
        """Return the first metric of a given metric type"""
        metric = self.get_monitoring_metric(metric_type)
        for component in metric.values():
            for m in component.values():
                return m

    def get_metric_unit(self, metric_type: MonitoringContextKeys):
        """Return the metric unit of a given metric"""
        first_metric = self.get_first_metric(metric_type)
        if first_metric:
            return first_metric.get_unit()
        return None

    def get_all_metrics(self, metric_type: MonitoringContextKeys, filter=None, names=None) -> list[MonitorMetric]:
        """Return all metrics of a given type.

        filter: substring that must be present in the component name (e.g. "Core").
        names: if provided, an explicit allow-list of exact component names to keep
               (e.g. {"Core_0", "Core_3"}); used to restrict rendering to the cores
               pinned during a benchmark.
        """
        metrics = []
        try:
            for metric in self.get_monitoring_metric(metric_type).values():
                for component_name, component in metric.items():
                    if names is not None and component_name not in names:
                        continue
                    if filter and filter not in component_name:
                        continue
                    # A component can be registered without ever reporting a
                    # sample (all-smi does that for the metrics a GPU does not
                    # support): there is nothing to render for it.
                    if component.get_mean():
                        metrics.append(component)
        except KeyError:
            pass
        return metrics

    def has_metrics(self, metric_type: MonitoringContextKeys, filter=None) -> bool:
        """Return True if any component of this type reported samples."""
        return bool(self.get_all_metrics(metric_type, filter))

    def pinned_core_names(self) -> set | None:
        """Return the set of monitoring component names matching the pinned cores.

        Returns None when the benchmark has no cpu pinning, so callers can fall
        back to rendering every core.
        """
        cpu_pin = self.cpu_pin()
        if not cpu_pin:
            return None
        return {f"Core_{core}" for core in cpu_pin}

    def pinned_cpu_range(self) -> str:
        """Return the pinned cpus as a condensed range string (e.g. '[0-12, 128-199]')."""
        cpu_pin = self.cpu_pin()
        if not cpu_pin:
            return "[]"
        # cpu_list_to_range sorts its argument in place, so pass a copy.
        return f"[{cpu_list_to_range(list(cpu_pin))}]"

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
        title = f"System:{d['serial']} {d['product']} Bios:v{d['bios']['version']} Linux Kernel:{k['release']}"
        title += (
            f"\nProcessor: {c.get('sockets', 1)}x {c['model']} - "
            f"{c['physical_cores']} physical cores and {c['numa_domains']} NUMA domains"
        )
        for label, text in gpu_description(self.get_trace().get_gpus()):
            title += f"\n{label}: {text}"
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

    def scaling_unit(self) -> ScalingUnit:
        """Return what one 'worker' of this benchmark is.

        The engines do not all stress the same kind of component, and the
        renderers need to name it, label the scaling axis with it and restrict a
        view to the ones a given benchmark used.
        """
        return GPU_SCALING_UNIT if Resource.GPU in self.resources() else CPU_SCALING_UNIT

    def resources(self) -> tuple[Resource, ...]:
        """Return the kinds of component this benchmark loads."""
        return engine_resources(self.engine())

    def gpu_list(self) -> list[int]:
        """Return the indexes of the GPUs used by this benchmark."""
        if self.get("gpu_pin") is not None:
            return self.get("gpu_pin")
        # Traces collected before selected_gpus was a hwbench keyword
        gpu_list = (self.get("custom_parameters") or {}).get("gpu_list", "")
        return [int(gpu) for gpu in gpu_list.split(",") if gpu]

    def gpu_names(self) -> set | None:
        """Return the monitoring component names matching the GPUs of this benchmark.

        Returns None when the benchmark uses no GPU, so callers can fall back to
        rendering every GPU of the system.
        """
        gpus = self.gpu_list()
        if not gpus:
            return None
        return {gpu_component_name(gpu) for gpu in gpus}

    def prepare_perf_metrics(self) -> tuple[list, str]:
        """Preparing a list of metrics and units based on the executed benchmark"""
        if self.engine() not in PERF_METRICS:
            fatal(f"Unsupported {self.engine()} engine")
        return PERF_METRICS[self.engine()](self)

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
        cpu_clock_cores=None,
        ipc=None,
        ipc_err=None,
        ipc_cores=None,
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
                        # The effective runtime must be within ~1sec compared to the expected duration.
                        # add_perf() is called many times per bench, so only warn once.
                        event_name = f"{self.trace.get_name()}/{self.get_bench_name()}"
                        if delta > 1 and event_name not in self.trace.incomplete_runtime_reported:
                            self.trace.incomplete_runtime_reported.add(event_name)
                            print(
                                f"{event_name} didn't completed on time. "
                                f"Effective_runtime={effective_runtime} vs {self.duration()} : delta=[{delta:.2f}s; {delta / self.duration() * 100:.2f}%]"
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
                        MonitoringContextKeys.PowerConsumption, self.get_trace().get_metric_name()
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
                        MonitoringContextKeys.PowerConsumption, self.get_trace().get_metric_name()
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
                            MonitoringContextKeys.PowerConsumption,
                            self.get_trace().get_metric_name(),
                        ).get_mean()
                    )
                    min_value = mean(
                        self.get_monitoring_metric_by_name(
                            MonitoringContextKeys.PowerConsumption,
                            self.get_trace().get_metric_name(),
                        ).get_min()
                    )
                    max_value = mean(
                        self.get_monitoring_metric_by_name(
                            MonitoringContextKeys.PowerConsumption,
                            self.get_trace().get_metric_name(),
                        ).get_max()
                    )
                    metric = (mean_value - min_value, max_value - mean_value)
                    if index is None:
                        watt_err.append(metric)
                    else:
                        watt_err[index] = metric

            # Both come from turbostat, which only runs on x86_64, so both can
            # legitimately be missing.
            self.__aggregate_family(
                MonitoringContextKeys.Freq, FreqContextKeys.CPU, cpu_clock, cpu_clock_err, cpu_clock_cores, index
            )
            self.__aggregate_family(MonitoringContextKeys.IPC, IPCContextKeys.CPU, ipc, ipc_err, ipc_cores, index)

        except ValueError:
            fatal(f"No {perf} found in {self.get_bench_name()}")

    def __aggregate_family(
        self,
        context: MonitoringContextKeys,
        family: StrEnum,
        target: list | None,
        target_err: list | None,
        names: set | None,
        index: int | None,
    ) -> None:
        """Average a per-component metric over one family, into target[index].

        family is the key the context is split by, i.e. FreqContextKeys.CPU for
        the cpu cores, which is not the 'Core_<n>' prefix their components are
        named after. names restricts the computation to the components used
        during the benchmark (the pinned cores, the burnt GPUs); None averages
        every component of the family. Nothing is recorded when none reported
        the metric.
        """
        if target is None:
            return

        try:
            components = self.get_monitoring_metric(context)
        except KeyError:
            return

        min_values = []
        mean_values = []
        max_values = []
        for name, metric in components.get(str(family), {}).items():
            if names is not None and name not in names:
                continue
            # MIN of min ? Mean of mean ? Max of max ?
            min_values.append(min(metric.get_min()))
            mean_values.append(mean(metric.get_mean()))
            max_values.append(max(metric.get_max()))

        if not mean_values:
            return

        mean_value = mean(mean_values)
        if index is None:
            target.append(mean_value)
        else:
            target[index] = mean_value

        # If we want to keep the error distribution to plot error bars
        if target_err is not None:
            metric_err = (mean_value - min(min_values), max(max_values) - mean_value)
            if index is None:
                target_err.append(metric_err)
            else:
                target_err[index] = metric_err

    def get_time_interval(self):
        return self.metrics[MonitoringMetadataKeys.iteration_time]

    def get_psu_power(self):
        psus = self.get_component(MonitoringContextKeys.PowerSupplies, PowerSuppliesContextKeys.BMC)
        power = 0
        if psus:
            power = [0] * len(psus[next(iter(psus))].get_samples())
            for psu in psus.values():
                count = 0
                for value in psu.get_mean():
                    power[count] = power[count] + value
                    count = count + 1
        return power

    def differences(self, other):
        """Compare if two Bench objects are similar"""
        for setting in self.settings():
            # We just want to ensure jobs are similar in their design
            # The skip_list is matching items that may vary across systems / runs
            skip_list = [
                "bogo",
                "monitoring",
                "cpu_pin",
                "detail",
                "avg_",
                "sum_",
                "memset",
                # The performance of the accelerators, and everything the
                # stressor measured about them, is what differs between two
                # servers running the same job.
                "score",
                "pantheon_results",
                "effective_runtime",
            ]

            # Skipping network results
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
        # Benchmarks already reported as not completing on time, so the warning
        # is printed only once per bench instead of on every add_perf() call.
        self.incomplete_runtime_reported: set = set()
        self.__load_file()

    def get_name(self) -> str:
        return self.logical_name

    def __load_file(self):
        """Validate the new trace file"""
        if not pathlib.Path(self.filename).is_file():
            raise ValueError(f"{self.filename} is not a valid file")

        # A compressed output directory of hwbench carries its results.json
        if tarfile.is_tarfile(self.filename):
            content = extract_results_from_archive(self.filename)
            if content is None:
                raise ValueError(f"{self.filename} does not contain a results.json")
        else:
            content = pathlib.Path(self.filename).read_bytes()

        # Can we load the input file as a valid json ?
        try:
            self.trace = json.loads(content)
        except ValueError:
            raise ValueError(f"{self.filename} is not a valid JSON file")

    def validate(self) -> None:
        # If no logical name was given, let's use the serial number as a default
        if not self.logical_name:
            self.logical_name = self.default_logical_name()
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

        if MonitoringContextKeys.PowerConsumption not in metrics:
            fatal(f"{self.filename}: Cannot find power consumption metrics")

        try:
            first_bench.get_monitoring_metric_by_name(MonitoringContextKeys.PowerConsumption, self.metric_name)
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
        power_metrics = [
            f"{name}.{v}"
            for name, value in first_bench.get_monitoring_metric(MonitoringContextKeys.PowerConsumption).items()
            for v in value
        ]
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

    def get_numa_nodes(self) -> dict[int, list[int]]:
        """Return the {numa domain: [logical cores]} mapping.

        Returns an empty dict for older traces that did not record it.
        """
        numa_nodes = self.get_cpu().get("numa_nodes")
        if not numa_nodes:
            return {}
        # JSON object keys are strings; expose them as ints.
        return {int(node): cores for node, cores in numa_nodes.items()}

    def get_numa_distances(self) -> dict[int, list[int]]:
        """Return the NUMA distance matrix ({source node: [latency to each node]}).

        Returns an empty dict for older traces that did not record it.
        """
        distances = self.get_cpu().get("numa_distances")
        if not distances:
            return {}
        return {int(node): latencies for node, latencies in distances.items()}

    def get_physical_cores(self):
        return self.get_cpu()["physical_cores"]

    def get_kernel(self):
        return self.get_environment().get("kernel")

    def get_gpus(self) -> dict[str, dict[str, Any]]:
        """Return the accelerator inventory, empty for a trace without any."""
        return self.get_hardware().get("gpus") or {}

    def get_chassis_serial(self):
        return self.get_dmi()["chassis"]["serial"]

    def get_chassis_product(self):
        return self.get_dmi()["chassis"]["product"]

    def get_server_serial(self):
        return self.get_dmi()["serial"]

    def default_logical_name(self) -> str:
        """The name of a trace given without logical_name: the serial number of the server,
        or its hostname when the DMI does not give one."""
        name = (self.get_server_serial() or "").strip() or (self.get_kernel() or {}).get("nodename")
        if not name:
            fatal(f"{self.filename}: no serial number nor hostname to name the trace, please give a logical_name")
        return name

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
