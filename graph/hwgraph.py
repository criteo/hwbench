#!/usr/bin/env python3
import argparse
import json
import pathlib
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import re
import sys
from typing import Any  # noqa: F401
from matplotlib.ticker import FuncFormatter, AutoMinorLocator, MultipleLocator
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
    ) -> None:
        self.ax2 = None
        self.args = args
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
        self.fig.clear()
        plt.close(self.fig)

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
        self,
        x_major_locator=0,
        x_minor_locator=0,
        y_locators=(None, None, None),
        legend=True,
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

        self.ax.set_ylim(None, ymin=0, ymax=ymax, emit=True, auto=True)
        # If we have a 2nd axis, let's prepare it
        if self.ax2:
            # Legend y1 at top left
            self.ax.legend(loc=2)
            # Legend y2 at top right
            self.ax2.legend(loc=1)
            self.ax2.set_ylim(None, ymin=0, ymax=self.y2_max, emit=True, auto=True)
            self.ax2.yaxis.set_major_formatter(FuncFormatter(self.human_format))
            self.fig.tight_layout()  # otherwise the right y-label is slightly clipped
        else:
            # Bar graphs do not need legend, let the caller disable it
            if legend:
                plt.legend()

        if x_major_locator:
            self.ax.set_xlim(None, xmin=0, emit=True)
            self.ax.xaxis.set_major_locator(
                MultipleLocator(x_major_locator),
            )

        if x_minor_locator:
            self.ax.xaxis.set_minor_locator(
                MultipleLocator(x_minor_locator),
            )

        self.ax.yaxis.set_major_formatter(FuncFormatter(self.human_format))
        self.prepare_grid()

    def human_format(self, num, pos=None):
        """Return format in Millions if necessary"""
        # This function is compatible with FuncFormatter and fmt
        unit = ""
        if num > 1e6:
            num *= 1e-6
            unit = "M"
        return f"{num:.2f}{unit}"

    def prepare_grid(self):
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
        # Retrieve the rendering file format
        file_format = self.args.format
        plt.savefig(
            f"{self.output_dir}/{self.filename}.{file_format}",
            format=file_format,
            dpi=self.args.dpi,
        )
        self.fig.clear()
        plt.close(self.fig)


def valid_trace_file(trace_arg: str) -> Trace:
    """Custom argparse type to decode and validate the trace files"""

    match = re.search(
        r"(?P<filename>.*):(?P<logical_name>.*):(?P<power_metric>.*)", trace_arg
    )
    if not match:
        raise argparse.ArgumentTypeError(
            f"{trace_arg} does not match 'filename:logical_name:power_metric' syntax"
        )

    return Trace(
        match.group("filename"),
        match.group("logical_name"),
        match.group("power_metric"),
    )


def compare_traces(args) -> None:
    """Check if benchmark definition are similar."""
    # To ensure a fair comparison, jobs must come from the same configuration file
    # But the number and names can be different regarding the hardware configuration.
    # To determine if traces can be compared, we'll compare only
    # the original configuration files, not the actual jobs.

    names = []
    for trace in args.traces:
        # Is the current trace config file matches the first trace ?
        if set(args.traces[0].get_original_config()).difference(
            trace.get_original_config()
        ):
            # If a trace is not having the same configuration file,
            # It's impossible to compare & graph the results.
            fatal(
                f"{trace.filename} is not having the same configuration file as previous traces"
            )
        if trace.get_name() in names:
            fatal(
                f"{trace.filename} is using '{trace.get_name()}' as logical_name while it's already in use"
            )
        else:
            names.append(trace.get_name())


def individual_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Plot bar graph to compare traces during individual benchmarks."""
    if args.verbose:
        print(f"Individual: rendering {job}")
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("individual")

    benches = args.traces[0].get_benches_by_job_per_emp(job)
    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for emp in benches.keys():
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        max_perf = {}  # type: dict[str, list]
        max_perfs_watt = {}  # type: dict[str, list]
        max_watt = {}  # type: dict[str, list]
        max_workers = {}  # type: dict[str, list]
        perf_list, unit = benches[emp]["metrics"]
        # For each metric we need to plot
        for perf in perf_list:
            if perf not in aggregated_perfs.keys():
                aggregated_perfs[perf] = {}
                aggregated_perfs_watt[perf] = {}
                aggregated_watt[perf] = {}
                max_perf[perf] = [0] * len(traces_name)
                max_perfs_watt[perf] = [0] * len(traces_name)
                max_watt[perf] = [0] * len(traces_name)
                max_workers[perf] = [0] * len(traces_name)
            # We want a datastructure where metrics of each iteration on the number of workers reports performance for each trace
            # It looks like :
            #  {2: [1264.58, 1063.5, 999.14, 1174.89],
            #   4: [2496.75, 2125.14, 1998.55, 2311.87],
            #   6: [3717.81, 3197.44, 2996.02, 3450.07],
            #   8: [4939.88, 4265.68, 4031.51, 4579.23],
            #  16: [9627.07, 8482.82, 7987.64, 8955.85],
            #  32: [17591.86, 17058.58, 15966.49, 17183.78],
            #  64: [0, 32507.33, 32468.21, 31999.65],
            #  96: [0, 0, 47910.2, 0]}
            # In this example 64 & 96 workers have partial values because some hosts didn't had enough cores to do it

            # For every trace file given at the command line
            index = 0
            for trace in args.traces:
                # Let's iterate on each Bench from this trace file matching this em
                for bench in trace.get_benches_by_job_per_emp(job)[emp]["bench"]:
                    if bench.workers() not in aggregated_perfs[perf].keys():
                        # If the worker count is not known yet, let's init all structures with as much zeros as the number of traces
                        # This will be the default value in case of the host doesn't have performance results
                        aggregated_perfs[perf][bench.workers()] = [0] * len(traces_name)
                        aggregated_perfs_watt[perf][bench.workers()] = [0] * len(
                            traces_name
                        )
                        aggregated_watt[perf][bench.workers()] = [0] * len(traces_name)
                    bench.add_perf(
                        perf,
                        aggregated_perfs[perf][bench.workers()],
                        aggregated_perfs_watt[perf][bench.workers()],
                        aggregated_watt[perf][bench.workers()],
                        index=index,
                    )

                    if bench.skipped():
                        max_workers[perf][index] = -1
                    temp_max_perf = aggregated_perfs[perf][bench.workers()][index]
                    if temp_max_perf > max_perf[perf][index]:
                        max_perf[perf][index] = temp_max_perf
                        max_perfs_watt[perf][index] = aggregated_perfs_watt[perf][
                            bench.workers()
                        ][index]
                        max_watt[perf][index] = aggregated_watt[perf][bench.workers()][
                            index
                        ]
                        max_workers[perf][index] = bench.workers()

                index = index + 1

        for graph_type in GRAPH_TYPES:
            # Let's render each performance graph
            graph_type_title = ""

            # for each performance metric we have to plot
            for perf in perf_list:
                clean_perf = perf.replace(" ", "").replace("/", "")
                y_label = unit
                outdir = temp_outdir.joinpath(graph_type)
                outfile = f"{bench.get_title_engine_name().replace(' ','_')}"

                # Let's define the tree architecture based on the benchmark profile
                # If the benchmark as multiple performance results, let's put then in a specific directory
                if len(perf_list) > 1:
                    outdir = outdir.joinpath(emp, perf)
                else:
                    outdir = outdir.joinpath(emp)

                # Select the proper datasource and titles/labels regarding the graph type
                if graph_type == "perf_watt":
                    graph_type_title = f"Individual {graph_type}: '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    graph_type_title += ": Bigger is better"
                    y_label = f"{unit} per Watt"
                    y_source = aggregated_perfs_watt
                    y_max = max_perfs_watt
                elif graph_type == "watts":
                    graph_type_title = (
                        f"Individual {graph_type}: {args.traces[0].get_metric_name()}"
                    )
                    graph_type_title += ": Lower is better"
                    y_label = "Watts"
                    y_source = aggregated_watt
                    y_max = max_watt
                else:
                    graph_type_title = (
                        f"Individual {graph_type}: {bench.get_title_engine_name()}"
                    )
                    graph_type_title += ": Bigger is better"
                    y_source = aggregated_perfs
                    y_max = max_perf

                # For each performance we have
                for worker in aggregated_perfs[perf]:
                    # Let's make a custom graph
                    title = f'{args.title}\n\n{graph_type_title} during "{bench.job_name()}" benchmark\n'
                    title += f"\nStressor: {worker} x {bench.engine()} "
                    title += f"{bench.engine_module()} "
                    title += f"{bench.engine_module_parameter()} for {bench.duration()} seconds"
                    y_serie = np.array(y_source[perf][worker])
                    graph = Graph(
                        args,
                        title,
                        "",
                        y_label,
                        outdir,
                        f"{worker}_workers_{outfile}{graph_type}_{clean_perf}",
                    )

                    # Prepare the plot for this benchmark
                    bar_colors = ["tab:red", "tab:blue", "tab:green", "tab:orange"]
                    # zorder=3 ensure the graph with be on top of the grid
                    graph.get_ax().bar(traces_name, y_serie, color=bar_colors, zorder=3)
                    graph.get_ax().bar_label(
                        graph.get_ax().containers[0],
                        label_type="center",
                        color="white",
                        fontsize=16,
                        fmt=graph.human_format,
                    )
                    graph.prepare_axes(legend=False)
                    graph.render()
                    rendered_graphs += 1

                # Now render the max performance graph
                # Concept is to show what every product reached as a maximum perf and plot them together
                # This way we have on a single graph showing the max of 32 cores vs a 48 cores vs a 64 cores.
                title = (
                    f'{args.title}\n\n{graph_type_title} during "{job}" benchmark\n'
                    f"\nProduct maximum performance during {bench.duration()} seconds"
                )
                y_serie = np.array(y_max[perf])
                graph = Graph(
                    args,
                    title,
                    "",
                    y_label,
                    outdir,
                    f"max_perf_{outfile}{graph_type}_{clean_perf}_{'_vs_'.join(traces_name).replace(' ', '')}",
                )

                # zorder=3 ensure the graph with be on top of the grid
                graph.get_ax().bar(traces_name, y_serie, color=bar_colors, zorder=3)

                # Let's put the normalized value in the center of the bar
                for trace_name in range(len(traces_name)):
                    if y_serie[trace_name] > 0:
                        plt.text(
                            trace_name,
                            y_serie[trace_name] // 2,
                            graph.human_format(y_serie[trace_name]),
                            ha="center",
                            color="white",
                            fontsize=16,
                        )

                # Add the number of workers, needed to reach that perf, below the trace name
                bar_labels = traces_name.copy()
                for trace_nb in range(len(traces_name)):
                    if max_workers[perf][trace_nb] < 0:
                        bar_labels[trace_nb] += "\nbenchmark skipped"
                    else:
                        bar_labels[
                            trace_nb
                        ] += f"\n{max_workers[perf][trace_nb]} workers"
                graph.get_ax().axes.xaxis.set_ticks(traces_name)
                graph.get_ax().set_xticklabels(bar_labels)

                graph.prepare_axes(legend=False)
                graph.render()
                rendered_graphs += 1
    return rendered_graphs


def scaling_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Render line graphs to compare performance scaling."""
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("scaling")

    # We extract the skeleton from the first trace
    # This will give us the name of the engine module parameters and
    # the metrics we need to plot
    benches = args.traces[0].get_benches_by_job_per_emp(job)
    if args.verbose:
        print(
            f"Scaling: working on job '{job}' : {len(benches.keys())} engine_module_parameter to render"
        )
    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for emp in benches.keys():
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        workers = {}  # type: dict[str, list]
        logical_core_per_worker = []
        perf_list, unit = benches[emp]["metrics"]
        # For each metric we need to plot
        for perf in perf_list:
            if perf not in aggregated_perfs.keys():
                aggregated_perfs[perf] = {}
                aggregated_perfs_watt[perf] = {}
                aggregated_watt[perf] = {}
            # For every trace file given at the command line
            for trace in args.traces:
                workers[trace.get_name()] = []
                # Let's iterate on each Bench from this trace file matching this emp
                for bench in trace.get_benches_by_job_per_emp(job)[emp]["bench"]:
                    # Workers list may be different between traces
                    # Let's keep a unique list of workers
                    if bench.workers() not in workers[trace.get_name()]:
                        workers[trace.get_name()].append(bench.workers())
                        pin = len(bench.cpu_pin())
                        # If there is no cpu_pin, we'll have the same number of workers
                        if pin == 0:
                            pin = bench.workers()
                        logical_core_per_worker.append(bench.workers() / pin)

                    # for each performance metric we have to plot,
                    # let's prepare the data set to plot
                    if trace.get_name() not in aggregated_perfs[perf].keys():
                        aggregated_perfs[perf][trace.get_name()] = []
                        aggregated_perfs_watt[perf][trace.get_name()] = []
                        aggregated_watt[perf][trace.get_name()] = []

                    bench.add_perf(
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
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}{'_vs_'.join(traces_name).replace(' ', '')}"
                    y_source = aggregated_perfs_watt
                elif "watts" in graph_type:
                    graph_type_title = (
                        f"Scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    )
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}{'_vs_'.join(traces_name).replace(' ', '')}"
                    y_label = "Watts"
                    y_source = aggregated_watt
                else:
                    graph_type_title = (
                        f"Scaling {graph_type}: {bench.get_title_engine_name()}"
                    )
                    outfile = f"scaling_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}{'_vs_'.join(traces_name).replace(' ', '')}"
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
                )

                # Traces are not ordered by growing cpu cores count
                # We need to prepare the x_serie to be sorted this way
                # The y_serie depends on the graph type
                for trace_name in aggregated_perfs[perf]:
                    # Each trace can have different numbers of workers based on the hardware setup
                    # So let's consider the list of x values per trace.
                    order = np.argsort(workers[trace_name])
                    x_serie = np.array(workers[trace_name])[order]
                    y_serie = np.array(y_source[perf][trace_name])[order]
                    graph.get_ax().plot(x_serie, y_serie, "", label=trace_name)

                graph.prepare_axes(8, 4)
                graph.render()
                rendered_graphs += 1

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
    # If user disabled the environmental graphs, return immediately
    if not args.no_env:
        print("environment: disabled by user")
        return rendered_graphs

    enclosure = args.traces[0].get_enclosure_serial()
    if enclosure:
        enclosures = [t.get_enclosure_serial() == enclosure for t in args.traces]
        # if all traces are from the same enclosure, let's enable the same_enclosure feature
        if enclosures.count(True) == len(args.traces):
            print(
                f"environment: All traces are from the same enclosure ({enclosure}), enabling --same-enclosure feature"
            )
            args.same_enclosure = True

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
    print(f"Individual: rendering {len(jobs)} jobs")
    for job in jobs:
        rendered_graphs += individual_graph(args, output_dir, job, traces_name)

    return rendered_graphs


def main():
    rendered_graphs = 0
    parser = argparse.ArgumentParser(
        prog="compgraph",
        description="compare hwbench results and plot them",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--traces",
        type=valid_trace_file,
        nargs="+",
        help="""List of benchmarks to compare.
Syntax: <json_filename>:<logical_name>:<power_metric>
json_file    : a results.json output file from hwbench
logical_name : a name to represent the trace in the graph
               if omitted, it will be replaced by the system serial number
               'CPU' magic keyword implicit the use of CPU model as logical_name but must be unique over all trace files.
power_metric : the name of a power metric, from the monitoring, to be used for 'watts' and 'perf per watt' graphs.
""",
    )
    parser.add_argument(
        "--no-env", help="Disable environmental graphs", action="store_false"
    )
    parser.add_argument("--title", help="Title of the graph")
    parser.add_argument("--dpi", help="Graph dpi", type=int, default="72")
    parser.add_argument("--width", help="Graph width", type=int, default="1920")
    parser.add_argument("--height", help="Graph height", type=int, default="1080")
    parser.add_argument(
        "--format",
        help="Graph file format",
        type=str,
        choices=["svg", "png"],
        default="svg",
    )
    parser.add_argument(
        "--engine",
        help="Select the matplotlib backend engine",
        choices=["pgf", "svg", "agg", "cairo"],
        default="cairo",
    )
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

    try:
        matplotlib.use(args.engine)
    except ValueError:
        fatal(f"Cannot load matplotlib backend engine {args.engine}")

    output_dir = pathlib.Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered_graphs += graph_environment(args, output_dir)
    compare_traces(args)
    rendered_graphs += plot_graphs(args, output_dir)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


if __name__ == "__main__":
    main()
