#!/usr/bin/env python3
import argparse
import json
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import re
import sys
from typing import Any  # noqa: F401
from matplotlib.ticker import MultipleLocator, AutoMinorLocator
from statistics import mean, stdev

MIN = "min"
MAX = "max"
MEAN = "mean"
ERROR = "error"
EVENTS = "events"
UNIT = "unit"
THERMAL = "thermal"
POWER = "power"
GRAPH_TYPES = ["perf", "perf_watt", "watts"]


def fatal(reason):
    """Print the error and exit 1."""
    sys.stderr.write("Fatal: {}\n".format(reason))
    sys.stderr.flush()
    sys.exit(1)


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
        return self.bench[setting]

    def cpu_pin(self) -> list:
        """Return the list of pinned cpu."""
        return self.get("cpu_pin")

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

    def add_perf(self, perf="", traces_perf=None, perf_watt=None, watt=None) -> None:
        """Extract performance and power efficiency"""
        try:
            if perf and traces_perf is not None:
                # Extracting performance
                value = self.get(perf)
                # but let's consider sum_speed for memrate runs
                if self.engine_module() in ["memrate"]:
                    value = self.get(perf)["sum_speed"]
                traces_perf.append(value)

            # If we want to keep the perf/watt ratio, let's compute it
            if perf_watt is not None:
                perf_watt.append(value / self.get_trace().get_metric_mean(self))

            # If we want to keep the power consumption, let's save it
            if watt is not None:
                watt.append(self.get_trace().get_metric_mean(self))
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
    def __init__(self, filename, name, metric_name):
        self.filename = filename
        self.name = name
        self.metric_name = metric_name
        self.__validate__()

    def get_name(self) -> str:
        return self.name

    def __validate__(self) -> None:
        """Validate the new trace file"""
        if not pathlib.Path(self.filename).is_file():
            raise ValueError(f"{self.filename} is not a valid file")

        # Can we load the input file as a valid json ?
        try:
            self.trace = json.loads(pathlib.Path(self.filename).read_bytes())
        except ValueError:
            raise ValueError(f"{self.filename} is not a valid JSON file")

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

    def get_environment(self) -> dict:
        return self.trace["environment"]

    def get_dmi(self):
        return self.get_hardware().get("dmi")

    def get_cpu(self):
        return self.get_hardware().get("cpu")

    def get_kernel(self):
        return self.get_environment().get("kernel")

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
        return self.get_trace()["bench"].keys()

    def first_bench(self) -> Bench:
        """Return the first bench"""
        return self.bench(next(iter(sorted(self.bench_list()))))

    def bench(self, bench_name: str) -> Bench:
        """Return one bench"""
        return Bench(self, bench_name)


class Graph:
    def __init__(
        self,
        args,
        title: str,
        xlabel: str,
        ylabel: str,
        output_dir,
        filename,
        square=False,
        show_source_file=None,
        plt_auto_close=True,
    ) -> None:
        self.ax2 = None
        self.args = args
        self.plt_auto_close = plt_auto_close
        self.fig, self.ax = plt.subplots()
        self.dpi = 100
        if square:
            self.fig.set_size_inches(args.width / self.dpi, args.width / self.dpi)
            self.ax.set_box_aspect(1)
        else:
            self.fig.set_size_inches(args.width / self.dpi, args.height / self.dpi)
        self.set_labels(xlabel, ylabel)
        self.set_xticks_style()
        self.set_title(title, show_source_file)
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self.set_filename(filename)

    def __del__(self):
        """Destruction will close all plots"""
        # Some graphs requires a deferred closing
        # Let the user defining this behavior
        if self.plt_auto_close:
            plt.close("all")

    def set_filename(self, filename: str):
        self.filename = filename

    def set_labels(self, xlabel: str, ylabel: str):
        """Set the x & y labels"""
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)

    def set_xticks_style(self):
        """Set the xtick style."""
        self.ax.tick_params(
            axis="x",
            which="minor",
            direction="out",
            colors="silver",
            grid_color="silver",
            grid_alpha=0.5,
            grid_linestyle="dotted",
        )

    def set_y2_axis(self, label: str, y2_max=None):
        """Add a second y axis"""
        ax2 = self.ax.twinx()  # instantiate a second axes that shares the same x-axis
        ax2.tick_params(axis="y")
        ax2.set_ylabel(label)
        self.ax2 = ax2
        self.y2_max = y2_max

    def prepare_axes(
        self, x_major_locator: int, x_minor_locator=0, y_locators=(None, None, None)
    ):
        """Set the ticks and axes limits."""
        # This should be called _after_ the ax.*plot calls
        ymax, y_major, y_minor = y_locators

        if y_major:
            self.ax.yaxis.set_major_locator(
                MultipleLocator(y_major),
            )

        if y_minor:
            self.ax.yaxis.set_minor_locator(
                MultipleLocator(y_minor),
            )

        self.ax.set_xlim(None, xmin=0, emit=True)
        self.ax.set_ylim(None, ymin=0, ymax=ymax, emit=True, auto=True)
        # If we have a 2nd axis, let's prepare it
        if self.ax2:
            # Legend y1 at top left
            self.ax.legend(loc=2)
            # Legend y2 at top right
            self.ax2.legend(loc=1)
            self.ax2.set_ylim(None, ymin=0, ymax=self.y2_max, emit=True, auto=True)
            self.fig.tight_layout()  # otherwise the right y-label is slightly clipped
        else:
            plt.legend()

        self.ax.xaxis.set_major_locator(
            MultipleLocator(x_major_locator),
        )

        if x_minor_locator:
            self.ax.xaxis.set_minor_locator(
                MultipleLocator(x_minor_locator),
            )

        self.ax.xaxis.set_minor_locator(AutoMinorLocator())
        plt.minorticks_on()

        self.ax.grid(which="major", linewidth=1)
        self.ax.grid(which="minor", linewidth=0.2, linestyle="dashed")

    def set_title(self, title, show_source_file=None):
        """Set the graph title"""
        self.ax.set_title(title)
        if show_source_file:
            # place a text box in upper left in axes coords
            props = dict(boxstyle="round", facecolor="white", alpha=0.5)
            self.ax.text(
                0,
                -0.1,
                f"data plotted from {show_source_file.get_filename()}",
                transform=self.ax.transAxes,
                fontsize=14,
                verticalalignment="top",
                bbox=props,
            )

    def get_ax(self):
        """Return the ax object."""
        return self.ax

    def get_ax2(self):
        """Return the ax2 object (for the 2nd y axis)."""
        return self.ax2

    def render(self):
        """Render the graph to a file."""
        plt.savefig(
            f"{self.output_dir}/{self.filename}.png", format="png", dpi=self.args.dpi
        )


def valid_trace_file(trace_arg: str) -> Trace:
    """Custom argparse type to decode and validate the trace files"""

    match = re.search(r"(?P<filename>.*):(?P<name>.*):(?P<power_metric>.*)", trace_arg)
    if not match:
        raise argparse.ArgumentTypeError(
            f"{trace_arg} does not match 'filename:name:power_metric' syntax"
        )

    return Trace(
        match.group("filename"), match.group("name"), match.group("power_metric")
    )


def compare_bench_profiles(args) -> None:
    """Check if benchmark profiles are similar."""
    # To ensure a fair comparison, all jobs must strictly identical
    # A next version will have to allow comparing jobs with different cpu types
    job_profile = None
    for trace in args.traces:
        if not job_profile:
            # Let's set the reference job
            job_profile = trace
        else:
            # Is the current list of benchmark name matching the previous one
            if set(job_profile.bench_list()).difference(trace.bench_list()):
                fatal(f"{trace.filename} is different from previous traces")

            for job in sorted(job_profile.bench_list()):
                # Let's check if the two bench are similar
                # If not, a fatal() will be triggered
                differences = job_profile.bench(job).differences(trace.bench(job))
                if differences:
                    fatal(differences)


def individual_graph(args, output_dir, bench_name: str, traces_name: list) -> int:
    """Plot bar graph to compare traces during individual benchmarks."""
    if args.verbose:
        print(f"Individual: rendering {bench_name}")
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("individual")

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)

    # Extract the performance metrics, units and name from this bench
    perf_list, unit = bench.prepare_perf_metrics()

    # Let's render all graphs types
    for graph_type in GRAPH_TYPES:
        # for each performance metric we have to plot
        for perf in perf_list:
            traces_perf = []  # type: list[float]
            traces_perf_watt = []  # type: list[float]
            traces_watt = []  # type: list[float]
            # for each input trace file
            for trace in args.traces:
                trace.bench(bench_name).add_perf(
                    perf, traces_perf, traces_perf_watt, traces_watt
                )

            clean_perf = perf.replace(" ", "").replace("/", "")
            outfile = f"{bench_name}_{clean_perf}_{bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}_{'_vs_'.join(traces_name)}"
            y_label = unit
            outdir = temp_outdir.joinpath(graph_type)
            if graph_type == "perf_watt":
                graph_type_title = f"'{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                y_label = f"{unit} per Watt"
                outfile = f"perfwatt_{outfile}"
                y_source = traces_perf_watt
            elif graph_type == "watts":
                graph_type_title = f"'{args.traces[0].get_metric_name()}'"
                outfile = f"watt_{outfile}"
                y_label = "Watts"
                y_source = traces_watt
            else:
                graph_type_title = f"'{bench.get_title_engine_name()} {perf}'"
                y_source = traces_perf

            title = (
                f'{args.title}\n\n{graph_type_title} during "{bench_name}" benchmark\n'
                f"\n{trace.bench(bench_name).title()}"
            )

            graph = Graph(
                args,
                title,
                "",
                y_label,
                outdir,
                outfile,
                plt_auto_close=False,
            )

            # Prepare the plot for this benchmark
            bar_colors = ["tab:red", "tab:blue", "tab:red", "tab:orange"]
            graph.get_ax().bar(traces_name, y_source, color=bar_colors)
            graph.render()
            rendered_graphs += 1

    plt.close("all")
    return rendered_graphs


def scaling_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Render line graphs to compare performance scaling."""
    if args.verbose:
        print(f"Scaling: working on {job}")
    rendered_graphs = 0
    selected_bench_names = []
    jobs = {}  # type: dict[str, list[Any]]
    metrics = {}
    temp_outdir = output_dir.joinpath("scaling")

    # First extract all subjobs expended from the same job
    for bench_name in sorted(args.traces[0].bench_list()):
        # As all traces are known to be similar, let's focus on a single trace to
        # compute the list of jobs to process and their associated metrics
        bench = args.traces[0].bench(bench_name)
        if bench.job_name() == job:
            selected_bench_names.append(bench_name)
            emp = bench.engine_module_parameter()
            if emp not in metrics:
                perf_list, unit = bench.prepare_perf_metrics()
                metrics[emp] = perf_list, unit
            if emp not in jobs.keys():
                jobs[emp] = []
            jobs[emp].append([bench_name, bench])

    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for parameter in jobs.keys():
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        workers = []
        logical_core_per_worker = []
        perf_list, unit = metrics[parameter]
        for bench_name, bench in jobs[parameter]:
            workers.append(bench.workers())
            pin = len(bench.cpu_pin())
            # If there is no cpu_pin, we'll have the same number of workers
            if pin == 0:
                pin = bench.workers()
            logical_core_per_worker.append(bench.workers() / pin)
            # for each performance metric we have to plot,
            # let's prepare the data set to plot
            for perf in perf_list:
                if perf not in aggregated_perfs.keys():
                    aggregated_perfs[perf] = {}
                    aggregated_perfs_watt[perf] = {}
                    aggregated_watt[perf] = {}
                # for each input trace file
                for trace in args.traces:
                    if trace.get_name() not in aggregated_perfs[perf].keys():
                        aggregated_perfs[perf][trace.get_name()] = []
                        aggregated_perfs_watt[perf][trace.get_name()] = []
                        aggregated_watt[perf][trace.get_name()] = []
                    trace.bench(bench_name).add_perf(
                        perf,
                        aggregated_perfs[perf][trace.get_name()],
                        aggregated_perfs_watt[perf][trace.get_name()],
                        aggregated_watt[perf][trace.get_name()],
                    )

        if len(logical_core_per_worker) == 1:
            print(f"Scaling: No scaling detected on {job}, skipping graph")
            break
        # Let's render all graphs types
        for graph_type in GRAPH_TYPES:
            # Let's render each performance graph
            graph_type_title = ""

            # for each performance metric we have to plot
            for perf in perf_list:
                clean_perf = perf.replace(" ", "").replace("/", "")
                y_label = unit
                outdir = temp_outdir.joinpath(graph_type)
                if "perf_watt" in graph_type:
                    graph_type_title = f"Scaling {graph_type}: '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    y_label = f"{unit} per Watt"
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}_{'_vs_'.join(traces_name)}"
                    y_source = aggregated_perfs_watt
                elif "watts" in graph_type:
                    graph_type_title = (
                        f"Scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    )
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}_{'_vs_'.join(traces_name)}"
                    y_label = "Watts"
                    y_source = aggregated_watt
                else:
                    graph_type_title = (
                        f"Scaling {graph_type}: {bench.get_title_engine_name()}"
                    )
                    outfile = f"scaling_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}_{'_vs_'.join(traces_name)}"
                    y_source = aggregated_perfs

                title = (
                    f'{args.title}\n\n{graph_type_title} via "{job}" benchmark job\n'
                    f"\n Stressor: "
                )
                title += (
                    f"{bench.get_title_engine_name()} for {bench.duration()} seconds"
                )
                xlabel = "Workers"
                # If we have a constent ratio between cores & workers, let's report them under the Xaxis
                if stdev(logical_core_per_worker) == 0:
                    cores = "cores"
                    if logical_core_per_worker[0] == 1:
                        cores = "core"
                    xlabel += f"\n({int(logical_core_per_worker[0])} logical {cores} per worker)"

                graph = Graph(
                    args,
                    title,
                    xlabel,
                    y_label,
                    outdir,
                    outfile,
                    square=True,
                    plt_auto_close=False,
                )

                # Traces are not ordered by growing cpu cores count
                # We need to prepare the x_serie to be sorted this way
                # The y_serie depends on the graph type
                for trace_name in aggregated_perfs[perf]:
                    order = np.argsort(workers)
                    x_serie = np.array(workers)[order]
                    y_serie = np.array(y_source[perf][trace_name])[order]
                    graph.get_ax().plot(x_serie, y_serie, "", label=trace_name)

                graph.prepare_axes(8, 4)
                graph.render()
                rendered_graphs += 1

            plt.close("all")

    return rendered_graphs


def generic_graph(
    args,
    output_dir,
    bench: Bench,
    component_name: str,
    item_title: str,
    second_axis=None,
) -> int:
    outfile = f"{component_name}"
    trace = bench.get_trace()

    if component_name == "temp":
        components = bench.get_components_by_unit("celsius")
    else:
        components = bench.get_components(component_name)
    if not components:
        print(f"{bench.get_bench_name()}: no {component_name}")
        return 0

    thermal_components = bench.get_components_by_unit("celsius")
    samples_count = bench.get_samples_count(components[0])

    title = (
        f'{item_title} during "{bench.get_bench_name()}" benchmark job\n'
        f"\n Stressor: "
    )
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph = Graph(
        args,
        title,
        "Time [seconds]",
        bench.get_monitoring_metric_unit(components[0]),
        output_dir.joinpath(
            f"{trace.get_name()}/{bench.get_bench_name()}/{component_name}"
        ),
        outfile,
        show_source_file=trace,
    )

    if second_axis:
        outfile += f"_vs_{second_axis}"
        graph.set_filename(outfile)
        if second_axis == THERMAL:
            graph.set_y2_axis("Thermal (°C)", 110)
        elif second_axis == POWER:
            graph.set_y2_axis("Power (Watts)")
            power_metrics = ["chassis"]
            if "enclosure" in bench.get_monitoring():
                power_metrics.append("enclosure")

    if args.verbose:
        print(
            f"{trace.get_name()}/{bench.get_bench_name()}: {len(components)} {component_name} to graph with {samples_count} samples"
        )

    time_interval = 10  # Hardcoded for now in benchmark.py
    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data2_serie = {}  # type: dict[str, list]
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            if component not in data_serie:
                data_serie[component] = []
            data_serie[component].append(bench.get_mean_events(component)[sample])

        if second_axis:
            if second_axis == THERMAL:
                for thermal_component in thermal_components:
                    if thermal_component not in data2_serie:
                        data2_serie[thermal_component] = []
                    data2_serie[thermal_component].append(
                        bench.get_mean_events(thermal_component)[sample]
                    )
            elif second_axis == POWER:
                for power_metric in power_metrics:
                    if power_metric not in data2_serie:
                        data2_serie[power_metric] = []
                    data2_serie[power_metric].append(
                        bench.get_mean_events(power_metric)[sample]
                    )

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]

    if second_axis:
        for data2_item in data2_serie:
            y2_serie = np.array(data2_serie[data2_item])[order]
            graph.get_ax2().plot(x_serie, y2_serie, "", label=data2_item, marker="D")

    for component in components:
        y_serie = np.array(data_serie[component])[order]
        graph.get_ax().plot(x_serie, y_serie, "", label=component)

    graph.prepare_axes(30, 15, (bench.get_monitoring_metric_axis(components[0])))

    graph.render()
    return 1


def yerr_graph(args, output_dir, bench: Bench, component_type: str, component: str):
    trace = bench.get_trace()
    samples_count = bench.get_samples_count(component)
    time_interval = 10

    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data_serie[MEAN] = []
    data_serie[ERROR] = []
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        mean_value = bench.get_mean_events(component)[sample]
        data_serie[ERROR].append(
            (
                mean_value - bench.get_min_events(component)[sample],
                bench.get_max_events(component)[sample] - mean_value,
            )
        )
        data_serie[MEAN].append(mean_value)

    title = (
        f'{component} during "{bench.get_bench_name()}" benchmark job\n'
        f"\n Stressor: "
    )
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        bench.get_monitoring_metric_unit(component),
        output_dir.joinpath(
            f"{trace.get_name()}/{bench.get_bench_name()}/{component_type}"
        ),
        component,
        show_source_file=trace,
    )

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    y_serie = np.array(data_serie[MEAN])[order]
    yerror_serie = np.array(data_serie[ERROR]).T
    graph.get_ax().errorbar(
        x_serie,
        y_serie,
        yerr=yerror_serie,
        fmt="-b",
        ecolor="r",
        capsize=4,
        label=component,
    )
    graph.prepare_axes(30, 15, bench.get_monitoring_metric_axis(component))
    graph.render()
    return 1


def graph_enclosure(args, bench_name, output_dir) -> int:
    """Graph enclosure vs sum of the chassis"""
    if args.verbose:
        print(f"enclosure: working on {bench_name}")

    outdir = output_dir.joinpath("enclosure")

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)
    base_outfile = f"{bench_name} {bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}_enclosure"
    y_label = "Watts"
    title = (
        f'{args.title}\n\nEnclosure power consumption during "{bench_name}" benchmark\n'
        f"\n{bench.title()}"
    )

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        y_label,
        outdir,
        f"time_watt_{base_outfile}",
    )

    time_interval = 10  # Hardcoded for now in benchmark.py
    time_serie = []
    sum_serie = {}  # type: dict[str, list]
    chassis_serie = {}  # type: dict[str, list]
    components = ["chassis", "enclosure"]
    samples_count = bench.get_samples_count("chassis")
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            if component not in sum_serie:
                sum_serie[component] = []

            # We want to get the sum of chassis vs enclosure
            if component == "chassis":
                value = 0
                # so let's add all chassis's value from each trace
                for trace in args.traces:
                    chassis_power = trace.bench(bench_name).get_mean_events(component)[
                        sample
                    ]
                    if trace.get_name() not in chassis_serie:
                        chassis_serie[trace.get_name()] = []
                    chassis_serie[trace.get_name()].append(chassis_power)
                    value += chassis_power
            else:
                value = bench.get_mean_events(component)[sample]
            sum_serie[component].append(value)
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    for component in components:
        y_serie = np.array(sum_serie[component])[order]
        curve_label = component
        if component == "chassis":
            curve_label = "sum of chassis"
        graph.get_ax().plot(x_serie, y_serie, "", label=curve_label)

    for trace in args.traces:
        y_serie = np.array(chassis_serie[trace.get_name()])[order]
        graph.get_ax().plot(x_serie, y_serie, "", label=trace.get_name())

    graph.prepare_axes(
        30,
        15,
        (None, 50, 25),
    )
    graph.render()

    return 1


def graph_fans(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    fans = bench.get_components("fan")
    if not fans:
        print(f"{bench_name}: no fans")
        return rendered_graphs
    for second_axis in [THERMAL, POWER]:
        rendered_graphs += generic_graph(
            args, output_dir, bench, "fan", "Fans speed", second_axis
        )

    for fan in fans:
        rendered_graphs += yerr_graph(args, output_dir, bench, "fan", fan)

    return rendered_graphs


def graph_cpu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    cpu_graphs = {}
    cpu_graphs["watt_core"] = "Core power consumption"
    cpu_graphs["package"] = "Package power consumption"
    cpu_graphs["mhz_core"] = "Core frequency"
    for graph in cpu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for second_axis in [None, THERMAL, POWER]:
            rendered_graphs += generic_graph(
                args, output_dir, bench, graph, cpu_graphs[graph], second_axis
            )

    return rendered_graphs


def graph_thermal(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    rendered_graphs += generic_graph(args, output_dir, bench, "temp", "Temperatures")
    return rendered_graphs


def graph_environment(args, output_dir) -> int:
    rendered_graphs = 0
    if args.same_enclosure:

        def valid_traces(args):
            chassis = [trace.get_chassis_serial() for trace in args.traces]
            # Let's ensure we don't have the same serial twice

            if len(chassis) == len(args.traces):
                # Let's ensure all traces has chassis and enclosure metrics
                for trace in args.traces:
                    try:
                        for metric in ["chassis", "enclosure"]:
                            trace.get_metric_mean(trace.first_bench(), metric)
                    except KeyError:
                        return f"environment: missing '{metric}' monitoric metric in {trace.get_filename()}, disabling same-enclosure print"
            else:
                return "environment: chassis are not unique, disabling same-enclosure print"
            return ""

        error_message = valid_traces(args)
        if not error_message:
            for bench_name in sorted(args.traces[0].bench_list()):
                rendered_graphs += graph_enclosure(args, bench_name, output_dir)
        else:
            print(error_message)

    for trace in args.traces:
        output_dir.joinpath(f"{trace.get_name()}").mkdir(parents=True, exist_ok=True)
        benches = trace.bench_list()
        print(
            f"environment: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})"
        )
        for bench_name in sorted(benches):
            rendered_graphs += graph_fans(args, trace, bench_name, output_dir)
            rendered_graphs += graph_cpu(args, trace, bench_name, output_dir)
            rendered_graphs += graph_thermal(args, trace, bench_name, output_dir)

    return rendered_graphs


def plot_graphs(args, output_dir) -> int:
    jobs = []
    rendered_graphs = 0
    for bench_name in sorted(args.traces[0].bench_list()):
        job_name = args.traces[0].bench(bench_name).job_name()
        # We want to keep a single job type
        # i.e an avx test can be rampuped from 1 to 64 cores, generating tens of sub jobs
        # We just want to keep the "avx" test as a reference, not all iterations
        if job_name not in jobs:
            jobs.append(job_name)

    traces_name = [trace.get_name() for trace in args.traces]

    # Let's generate the scaling graphs
    print(f"Scaling: {len(jobs)} jobs")
    for job in jobs:
        rendered_graphs += scaling_graph(args, output_dir, job, traces_name)

    # Let's generate the unitary comparing graphs
    benches = args.traces[0].bench_list()
    print(f"Individual: rendering {len(benches)} jobs")
    for bench_name in sorted(benches):
        rendered_graphs += individual_graph(args, output_dir, bench_name, traces_name)

    return rendered_graphs


def main():
    rendered_graphs = 0
    parser = argparse.ArgumentParser(
        prog="compgraph",
        description="compare hwbench results and plot them",
    )
    parser.add_argument(
        "--traces",
        type=valid_trace_file,
        nargs="+",
        help="List of benchmarks to compare",
    )
    parser.add_argument("--title", help="Title of the graph")
    parser.add_argument("--dpi", help="PNG dpi", type=int, default="72")
    parser.add_argument("--width", help="PNG width", type=int, default="1920")
    parser.add_argument("--height", help="PNG height", type=int, default="1080")
    parser.add_argument("--outdir", help="Name of the output directory", required=True)
    parser.add_argument(
        "--same-enclosure",
        help="All traces are from the same enclosure",
        action="store_true",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode",
    )

    args = parser.parse_args()
    output_dir = pathlib.Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered_graphs += graph_environment(args, output_dir)
    compare_bench_profiles(args)
    rendered_graphs += plot_graphs(args, output_dir)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


if __name__ == "__main__":
    main()
