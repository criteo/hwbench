#!/usr/bin/env python3
import argparse
import json
import pathlib
import matplotlib.pyplot as plt
import numpy as np
import re
import sys
import tempfile
from typing import Any  # noqa: F401
from matplotlib.ticker import MultipleLocator
from statistics import mean, stdev

MIN = "min"
MAX = "max"
MEAN = "mean"
EVENTS = "events"
UNIT = "unit"

GRAPH_TYPES = ["perf", "perf_watt"]


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

    def get_mean_events(self, metric_name: str) -> list:
        """Return the mean values of metric_name"""
        return self.get_monitoring_metric(metric_name)[MEAN].get(EVENTS)

    def get_monitoring(self) -> dict:
        """Return the monitoring metrics."""
        return self.get("monitoring")

    def get_monitoring_metric(self, metric_name) -> dict:
        """Return one monitoring metric."""
        return self.get_monitoring()[metric_name]

    def title(self) -> str:
        """Prepare the benchmark title name."""
        title = f"Stressor: {self.workers()} x {self.engine()} "
        title += f"{self.engine_module()} "
        title += f"{self.engine_module_parameter()} for {self.duration()} seconds"
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
        if self.engine() not in ["stressng"]:
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

        return perf_list, unit

    def get_trace(self):
        """Return the Trace object associated to this benchmark"""
        return self.trace

    def add_perf(self, perf: str, traces_perf: list, traces_watt=None) -> None:
        """Extract performance and power efficiency"""
        try:
            # Extracting performance
            value = self.get(perf)
            # but let's consider sum_speed for memrate runs
            if self.engine_module() in ["memrate"]:
                value = self.get(perf)["sum_speed"]
            traces_perf.append(value)

            # If we want to keep the perf/watt ratio, let's compute it
            if traces_watt is not None:
                traces_watt.append(value / self.get_trace().get_metric_mean(self))
        except ValueError:
            fatal(f"No {perf} found in {self.get_bench_name()}")

    def differences(self, other) -> str:
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
            first_bench = self.bench(next(iter(self.bench_list())))
            isinstance(self.get_metric_mean(first_bench), float)
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

    def get_metric_name(self) -> str:
        """Return the metric name"""
        return self.metric_name

    def get_metric_mean(self, bench: Bench) -> float:
        """Return the mean of chosen metric"""
        # return mean(get_mean_events(bench.get_monitoring_metric(self.metric_name)))
        return mean(bench.get_mean_events(self.metric_name))

    def bench_list(self) -> dict:
        """Return the list of benches"""
        return self.get_trace()["bench"].keys()

    def bench(self, bench_name: str) -> Bench:
        """Return one bench"""
        return Bench(self, bench_name)


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
    outdir = output_dir.joinpath("individual")
    outdir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots()
    my_dpi = 100
    fig.set_dpi(my_dpi)
    fig.set_size_inches(args.width / my_dpi, args.height / my_dpi)

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)

    # Extract the performance metrics, units and name from this bench
    perf_list, unit = bench.prepare_perf_metrics()

    # for each performance metric we have to plot
    for perf in perf_list:
        traces_perf = []  # type: list[float]
        # for each input trace file
        for trace in args.traces:
            trace.bench(bench_name).add_perf(perf, traces_perf)

        # Prepare the plot for this benchmark
        bar_colors = ["tab:red", "tab:blue", "tab:red", "tab:orange"]
        ax.bar(traces_name, traces_perf, color=bar_colors)
        title = (
            f'{args.title}\n\n{bench.engine_module()} {perf} during "{bench_name}" benchmark\n'
            f"\n{trace.bench(bench_name).title()}"
        )
        ax.set_ylabel(f"{unit}")
        ax.set_title(title)
        plt.grid(True)
        clean_perf = perf.replace(" ", "").replace("/", "")
        outfile = f"{bench_name}_{clean_perf}_{bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}_{'_vs_'.join(traces_name)}"
        plt.savefig(f"{outdir}/{outfile}.png", format="png")
        rendered_graphs += 1

    plt.close("all")
    return rendered_graphs


def scaling_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Render line graphs to compare performance scaling."""
    if args.verbose:
        print(f"Scaling: rendering {job}")
    rendered_graphs = 0
    selected_bench_names = []
    jobs = {}  # type: dict[str, list[Any]]
    metrics = {}
    for graph_type in ["scaling", "scaling_watt"]:
        output_dir.joinpath(f"{graph_type}").mkdir(parents=True, exist_ok=True)

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
        workers = []
        logical_core_per_worker = []
        perf_list, unit = metrics[parameter]
        for bench_name, bench in jobs[parameter]:
            workers.append(bench.workers())
            logical_core_per_worker.append(bench.workers() / len(bench.cpu_pin()))
            # for each performance metric we have to plot,
            # let's prepare the data set to plot
            for perf in perf_list:
                if perf not in aggregated_perfs.keys():
                    aggregated_perfs[perf] = {}
                    aggregated_perfs_watt[perf] = {}
                # for each input trace file
                for trace in args.traces:
                    if trace.get_name() not in aggregated_perfs[perf].keys():
                        aggregated_perfs[perf][trace.get_name()] = []
                        aggregated_perfs_watt[perf][trace.get_name()] = []
                    trace.bench(bench_name).add_perf(
                        perf,
                        aggregated_perfs[perf][trace.get_name()],
                        aggregated_perfs_watt[perf][trace.get_name()],
                    )

        # Let's render all graphs types
        for graph_type in GRAPH_TYPES:
            # Let's render each performance graph
            graph_type_title = ""

            # for each performance metric we have to plot
            for perf in perf_list:
                fig, ax = plt.subplots()
                my_dpi = 100
                fig.set_dpi(my_dpi)
                # We force the args.width on both dimension to ensure a square graph
                fig.set_size_inches(args.width / my_dpi, args.width / my_dpi)
                clean_perf = perf.replace(" ", "").replace("/", "")
                if "watt" in graph_type:
                    graph_type_title = f"Scaling {graph_type}: '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    ax.set_ylabel(f"{unit} per Watt")
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}_{'_vs_'.join(traces_name)}"
                    outdir = output_dir.joinpath("scaling_watt")
                else:
                    graph_type_title = (
                        f"Scaling {graph_type}: {bench.get_title_engine_name()}"
                    )
                    ax.set_ylabel(unit)
                    outfile = f"scaling_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}_{'_vs_'.join(traces_name)}"
                    outdir = output_dir.joinpath("scaling")

                # We want Xaxis to be plotted modulo 8 for the major and modulo 4 for the minor
                ax.xaxis.set_major_locator(
                    MultipleLocator(8),
                )
                ax.xaxis.set_minor_locator(
                    MultipleLocator(4),
                )

                ax.tick_params(
                    axis="x",
                    which="minor",
                    direction="out",
                    colors="silver",
                    grid_color="silver",
                    grid_alpha=0.5,
                    grid_linestyle="dotted",
                )

                # Traces are not ordered by growing cpu cores count
                # We need to prepare the x_serie to be sorted this way
                # The y_serie depends on the graph type
                for trace_name in aggregated_perfs[perf]:
                    order = np.argsort(workers)
                    x_serie = np.array(workers)[order]
                    y_source = aggregated_perfs
                    if "watt" in graph_type:
                        y_source = aggregated_perfs_watt
                    y_serie = np.array(y_source[perf][trace_name])[order]
                    ax.plot(x_serie, y_serie, "", label=trace_name)

                title = (
                    f'{args.title}\n\n{graph_type_title} via "{job}" benchmark job\n'
                    f"\n Stressor: "
                )
                title += (
                    f"{bench.get_title_engine_name()} for {bench.duration()} seconds"
                )
                ax.set_title(title)

                xlabel = "Workers"
                # If we have a constent ratio between cores & workers, let's report them under the Xaxis
                if stdev(logical_core_per_worker) == 0:
                    cores = "cores"
                    if logical_core_per_worker[0] == 1:
                        cores = "core"
                    xlabel += f"\n({int(logical_core_per_worker[0])} logical {cores} per worker)"
                ax.set_xlabel(xlabel)
                ax.set_box_aspect(1)
                ax.set_xticks(range(0, int(max(workers) + 1), 8), minor=False)
                # We want to force some axis constraints
                ax.set_xlim(None, xmin=0, emit=True)
                ax.set_ylim(None, ymin=0, emit=True, auto=True)
                plt.minorticks_on()
                plt.grid(which="both")
                plt.legend()
                plt.savefig(f"{outdir}/{outfile}.png", format="png")
                rendered_graphs += 1

            plt.close("all")

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
    print(f"Scaling: rendering {len(jobs)} jobs")
    for job in jobs:
        rendered_graphs += scaling_graph(args, output_dir, job, traces_name)

    # Let's generate the unitary comparing graphs
    benches = args.traces[0].bench_list()
    print(f"Individual: rendering {len(benches)} jobs")
    for bench_name in sorted(benches):
        rendered_graphs += individual_graph(args, output_dir, bench_name, traces_name)

    return rendered_graphs


def main():
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
    parser.add_argument("--width", help="PNG width", type=int, default="1920")
    parser.add_argument("--height", help="PNG height", type=int, default="1080")
    parser.add_argument("--outdir", help="Name of the output directory")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode",
    )

    args = parser.parse_args()
    if not args.outdir:
        output_dir = tempfile.TemporaryDirectory(delete=False)
    else:
        output_dir = pathlib.Path(args.outdir)
        output_dir.mkdir(parents=True, exist_ok=True)

    compare_bench_profiles(args)
    rendered_graphs = plot_graphs(args, output_dir)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


if __name__ == "__main__":
    main()
