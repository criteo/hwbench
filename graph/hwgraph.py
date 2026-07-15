#!/usr/bin/env python3
import argparse
import os
import pathlib
import pickle
import re
import shlex
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from graph.graph import InvalidValue
from hwbench.bench.monitoring_structs import (
    FansContextKeys,
    MonitorContextKeys,
    MonitoringContextKeys,
    PowerConsumptionContextKeys,
)

try:
    from graph.chassis import graph_chassis
    from graph.common import fatal
    from graph.graph import (
        cpu_distribution_graph,
        generic_graph,
        init_matplotlib,
        numa_aggregated_components,
        numa_distance_heatmap,
        numa_distribution_graph,
        numa_performance_heatmap,
        write_benchmarks_summary,
        yerr_graph,
    )
    from graph.group import graph_group_env
    from graph.scaling import performance_scaling_graph
    from graph.trace import Event, Trace
    from graph.versus import (
        max_versus_graph,
        render_versus_scorecard,
        write_scaling_comparison,
        write_scaling_step_comparisons,
    )
    from hwbench.bench.monitoring_structs import (
        PowerCategories,
    )
except ImportError as exc:
    print(exc)
    print(
        'Could not start hwgraph: did you make sure to also install the "graph" optional dependencies using `uv sync --extra graph` or `pip install hwbench[graph]`?'
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Multiprocessing infrastructure
# ---------------------------------------------------------------------------

# Module-level global used by worker processes to access shared data
_pool_args = None


def _init_pool_worker(args_data):
    """Initialize a worker process with shared data and matplotlib backend."""
    global _pool_args
    _pool_args = pickle.loads(args_data)
    init_matplotlib(_pool_args)


def _execute_pool_task(task):
    """Execute a single graph generation task in a worker process."""
    func, *func_args = task
    return func(*func_args)


def _task_env_bench(trace_idx, bench_name, output_dir_str):
    """Generate all environment graphs for a single (trace, bench) pair."""
    global _pool_args
    args = _pool_args
    trace = args.traces[trace_idx]
    output_dir = pathlib.Path(output_dir_str)
    count = 0
    count += graph_monitoring_metrics(args, trace, bench_name, output_dir)
    count += graph_fans(args, trace, bench_name, output_dir)
    count += graph_cpu(args, trace, bench_name, output_dir)
    count += graph_cpu_numa(args, trace, bench_name, output_dir)
    count += graph_pdu(args, trace, bench_name, output_dir)
    count += graph_thermal(args, trace, bench_name, output_dir)
    return count


def _task_numa_distance(trace_idx, output_dir_str):
    """Generate the per-host NUMA distance heatmap (once per trace)."""
    global _pool_args
    return numa_distance_heatmap(_pool_args, pathlib.Path(output_dir_str), _pool_args.traces[trace_idx])


def _task_chassis(bench_name, output_dir_str):
    """Generate chassis graphs for a single bench."""
    global _pool_args
    return graph_chassis(_pool_args, bench_name, pathlib.Path(output_dir_str))


def _task_group(bench_name, output_dir_str):
    """Generate group graphs for a single bench."""
    global _pool_args
    return graph_group_env(_pool_args, bench_name, pathlib.Path(output_dir_str))


def _task_scaling(job, output_dir_str, traces_name):
    """Generate performance scaling graphs for a job."""
    global _pool_args
    return performance_scaling_graph(_pool_args, pathlib.Path(output_dir_str), job, traces_name)


def _task_scaling_comparison(output_dir_str):
    """Write the traces-comparison summaries + exec-summary scorecard (reference = first trace)."""
    global _pool_args
    output_dir = pathlib.Path(output_dir_str)
    count = write_scaling_comparison(_pool_args, output_dir)
    count += render_versus_scorecard(_pool_args, output_dir)
    # Same comparison, but one file per scaling step under scaling/.
    count += write_scaling_step_comparisons(_pool_args, output_dir)
    return count


def _task_versus(job, output_dir_str, traces_name):
    """Generate max versus graphs for a job."""
    global _pool_args
    return max_versus_graph(_pool_args, pathlib.Path(output_dir_str), job, traces_name)


# ---------------------------------------------------------------------------
# Task collection functions
# ---------------------------------------------------------------------------


def _collect_group_tasks(args, output_dir):
    """Collect group graph tasks."""
    tasks = []
    if not args.same_group:
        return tasks
    # Graphs below are per group
    output_dir = output_dir.joinpath("by_group")
    for trace in args.traces:
        try:
            metric = f"BMC/{PowerCategories.SERVER}"
            trace.first_bench().get_single_metric(
                MonitoringContextKeys.PowerConsumption,
                PowerConsumptionContextKeys.BMC,
                PowerCategories.SERVER,
            )
            metric = "CPU/package"
            trace.first_bench().get_single_metric(
                MonitoringContextKeys.PowerConsumption, PowerConsumptionContextKeys.CPU, "package"
            )
        except KeyError:
            fatal(f"group: missing '{metric}' monitoric metric in {trace.get_filename()}")
    print(f"group: rendering {len(args.traces[0].bench_list())} jobs")
    for bench_name in sorted(args.traces[0].bench_list()):
        tasks.append((_task_group, bench_name, str(output_dir)))
    return tasks


def _collect_environment_tasks(args, output_dir):
    """Collect environment graph tasks."""
    tasks = []
    # If user disabled the environmental graphs, return immediately
    if not args.no_env:
        print("environment: disabled by user")
        return tasks

    output_dir = output_dir.joinpath("environment")

    chassis = args.traces[0].get_chassis_serial()
    if chassis:
        all_chassis = [t.get_chassis_serial() == chassis for t in args.traces]
        # if all traces are from the same chassis, let's enable the same_chassis feature
        if all_chassis.count(True) == len(args.traces) and len(args.traces) > 1:
            print(f"environment: All traces are from the same chassis ({chassis}), enabling --same-chassis feature")
            args.same_chassis = True

    if args.same_chassis:

        def valid_traces(args):
            server = [trace.get_server_serial() for trace in args.traces]
            # Let's ensure we don't have the same serial twice

            if len(server) == len(args.traces):
                # Let's ensure all traces has server and chassis metrics
                for trace in args.traces:
                    try:
                        for metric in [
                            PowerCategories.CHASSIS,
                            PowerCategories.SERVER,
                        ]:
                            trace.first_bench().get_single_metric(
                                MonitoringContextKeys.PowerConsumption,
                                PowerConsumptionContextKeys.BMC,
                                metric,
                            )
                    except KeyError:
                        return f"environment: missing '{metric}' monitoric metric in {trace.get_filename()}, disabling same-enclosure print"
            else:
                return "environment: server are not unique, disabling same-chassis print"
            return ""

        error_message = valid_traces(args)
        if not error_message:
            for bench_name in sorted(args.traces[0].bench_list()):
                tasks.append((_task_chassis, bench_name, str(output_dir.joinpath("by_chassis"))))
        else:
            print(error_message)

    # Graphs below are per host
    host_output_dir = output_dir.joinpath("by_host")
    for trace_idx, trace in enumerate(args.traces):
        host_output_dir.joinpath(f"{trace.get_name()}").mkdir(parents=True, exist_ok=True)
        benches = trace.bench_list()
        print(f"environment: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})")
        for bench_name in sorted(benches):
            tasks.append((_task_env_bench, trace_idx, bench_name, str(host_output_dir)))
        # One NUMA distance heatmap per host, not tied to any benchmark.
        tasks.append((_task_numa_distance, trace_idx, str(host_output_dir)))

    return tasks


def _collect_plot_tasks(args, output_dir):
    """Collect scaling and versus graph tasks."""
    tasks = []
    jobs = []
    for bench_name in sorted(args.traces[0].bench_list()):
        job_name = args.traces[0].bench(bench_name).job_name()
        # We want to keep a single job type
        # i.e an avx test can be rampuped from 1 to 64 cores, generating tens of sub jobs
        # We just want to keep the "avx" test as a reference, not all iterations
        if job_name not in jobs:
            jobs.append(job_name)

    traces_name = [trace.get_name() for trace in args.traces]

    if not args.no_scaling:
        print("Performance scaling: disabled by user")
    else:
        # Let's generate the scaling graphs
        print(f"Performance scaling: rendering {len(jobs)} jobs")
        for job in jobs:
            tasks.append((_task_scaling, job, str(output_dir), traces_name))

    if not args.no_versus:
        print("Max versus: disabled by user")
    else:
        # Let's generate the unitary comparing graphs
        if len(traces_name) > 1:
            print(f"Max versus: rendering {len(jobs)} jobs")
            for job in jobs:
                tasks.append((_task_versus, job, str(output_dir), traces_name))
            # Text reports comparing every trace to the first (reference): one at
            # full load covering all benchmarks (max_versus/benchmarks_summary.txt)
            # plus one per scaling step under scaling/.
            tasks.append((_task_scaling_comparison, str(output_dir)))
        else:
            print("Max versus: skipped as at least 2 traces are necessary for this mode")

    return tasks


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------


def _execute_tasks(args, tasks):
    """Execute graph generation tasks, using multiprocessing when jobs > 1."""
    global _pool_args
    num_workers = max(1, min(args.jobs, len(tasks)))
    rendered_graphs = 0

    if num_workers <= 1:
        # Single-process mode: execute tasks sequentially
        _pool_args = args
        for task in tasks:
            try:
                rendered_graphs += _execute_pool_task(task)
            except Exception as e:
                print(f"Error generating graph: {e}")
    else:
        # Multi-process mode
        print(f"Rendering graphs using {num_workers} parallel workers for {len(tasks)} tasks")
        args_data = pickle.dumps(args, protocol=pickle.HIGHEST_PROTOCOL)
        with ProcessPoolExecutor(
            max_workers=num_workers,
            initializer=_init_pool_worker,
            initargs=(args_data,),
        ) as pool:
            futures = {pool.submit(_execute_pool_task, task): i for i, task in enumerate(tasks)}
            for completed, future in enumerate(as_completed(futures), 1):
                try:
                    rendered_graphs += future.result()
                except Exception as e:
                    print(f"Error generating graph (task {futures[future]}): {e}")
                if completed % 10 == 0 or completed == len(tasks):
                    print(f"Progress: {completed}/{len(tasks)} tasks completed ({rendered_graphs} graphs rendered)")

    return rendered_graphs


# ---------------------------------------------------------------------------
# Argument validators
# ---------------------------------------------------------------------------


def valid_trace_file(trace_arg: str) -> Trace:
    """Custom argparse type to decode and validate the trace files"""

    match = re.search(r"(?P<filename>.*):(?P<logical_name>.*):(?P<power_metric>.*)", trace_arg)
    if not match:
        raise argparse.ArgumentTypeError(f"{trace_arg} does not match 'filename:logical_name:power_metric' syntax")

    try:
        trace = Trace(
            match.group("filename"),
            match.group("logical_name"),
            match.group("power_metric"),
        )
        trace.validate()
        return trace
    except BaseException as e:
        # Print validation failure and pass it on
        print(f"Trace validation failure: {e}")
        raise e


def valid_events(event_arg: str) -> Event:
    """Custom argparse type to decode and validate the event list"""

    match = re.search(r"(?P<event>.*):(?P<start>.*):(?P<duration>.*)", event_arg)
    if not match:
        raise argparse.ArgumentTypeError(f"{event_arg} does not match 'event_name:start_time:duration' syntax")

    try:
        event = Event(
            match.group("event"),
            int(match.group("start")),
            int(match.group("duration")),
        )
        event.validate()
        return event
    except BaseException as e:
        # Print validation failure and pass it on
        print(f"Event validation failure: {e}")
        raise e


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def list_metrics_in_trace(args: argparse.Namespace):
    """List power metrics of a trace file"""
    Trace(args.trace).list_power_metrics()
    sys.exit(0)


def render_traces(args: argparse.Namespace):
    """Render the trace files passed in arguments"""
    init_matplotlib(args)
    output_dir = pathlib.Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compare_traces(args)
    generate_stats(args)

    # Write the per-host benchmarks summary text table before rendering any graph,
    # so the key to what each benchmark tests is available up front. args.no_env is
    # True when environmental graphs are enabled (--no-env, store_false, disables).
    if args.no_env:
        host_output_dir = output_dir.joinpath("environment", "by_host")
        for trace in args.traces:
            write_benchmarks_summary(args, host_output_dir, trace)

    # Collect all graph generation tasks
    # (This also performs validation and creates output directories)
    tasks = []
    tasks.extend(_collect_group_tasks(args, output_dir))
    tasks.extend(_collect_environment_tasks(args, output_dir))
    tasks.extend(_collect_plot_tasks(args, output_dir))

    if not tasks:
        print("No graphs to render")
        return

    rendered_graphs = _execute_tasks(args, tasks)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


# ---------------------------------------------------------------------------
# Sequential helpers (unchanged, used by task workers)
# ---------------------------------------------------------------------------


def generate_stats(args) -> None:
    if not args.no_stats:
        return
    for trace in args.traces:
        benches = trace.bench_list()
        print(f"stats: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})")
        max_power = {key: ("", 0.0) for key in PowerConsumptionContextKeys}
        for bench_name in sorted(benches):
            bench = trace.bench(bench_name)
            for metric_name in PowerConsumptionContextKeys:
                try:
                    for m in [MonitoringContextKeys.PowerConsumption]:
                        metrics = bench.get_component(m, metric_name)
                        if metrics:
                            for metric in metrics:
                                # If a metric has no measure, let's ignore it
                                if len(metrics[metric].get_samples()) == 0:
                                    if args.verbose:
                                        print(
                                            f"{bench_name}: No samples found in {metric_name}.{metric}, ignoring metric."
                                        )
                                    continue
                                else:
                                    max_values = metrics[metric].get_max()
                                    if max_values:
                                        current_max = max(max_values)
                                        if current_max > max_power[metric_name][1]:
                                            max_power[metric_name] = (bench_name, float(current_max))
                                            bench.get_metric_unit(m)
                except KeyError:
                    continue

    for metric in [MonitoringContextKeys.PowerConsumption]:
        print(f"{str(metric):}")
        for metric_name in PowerConsumptionContextKeys:
            # Only report a max when data was actually found (a bench was recorded).
            if max_power[metric_name][0]:
                print(
                    f"    {metric_name} max : {max_power[metric_name][1]:.2f} {bench.get_metric_unit(metric)} in {max_power[metric_name][0]}"
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
        if args.traces[0].get_original_config() != trace.get_original_config():
            # If a trace is not having the same configuration file,
            # It's impossible to compare & graph the results.
            fatal(f"{trace.filename} is not having the same configuration file as previous traces")
        if trace.get_name() in names:
            fatal(f"{trace.filename} is using '{trace.get_name()}' as logical_name while it's already in use")
        else:
            names.append(trace.get_name())


def graph_monitoring_metrics(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    for metric_name in MonitorContextKeys:
        try:
            metrics = bench.get_component(MonitoringContextKeys.Monitor, metric_name)
        except KeyError:
            print(f"{bench_name}: {metric_name} metric is not present in trace file, skipping.")
        if metrics:
            for metric in metrics:
                # If a metric has no measure, let's ignore it
                if len(metrics[metric].get_samples()) == 0:
                    if args.verbose:
                        print(f"{bench_name}: No samples found in {metric_name}.{metric}, ignoring metric.")
                else:
                    try:
                        rendered_graphs += yerr_graph(
                            args,
                            output_dir,
                            bench,
                            MonitoringContextKeys.Monitor,
                            metrics[metric],
                            prefix=f"{metric_name}.",
                        )
                    except InvalidValue as e:
                        print(f"An error occurred while generating the graph for {bench_name} ({metric_name}): {e}")

    return rendered_graphs


def graph_fans(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    fans = bench.get_component(MonitoringContextKeys.Fans, FansContextKeys.Fan)
    if not fans:
        print(f"{bench_name}: no fans")
        return rendered_graphs
    for second_axis in [MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
        rendered_graphs += generic_graph(args, output_dir, bench, MonitoringContextKeys.Fans, "Fans speed", second_axis)

    for fan in fans:
        rendered_graphs += yerr_graph(args, output_dir, bench, MonitoringContextKeys.Fans, fans[fan])

    return rendered_graphs


def graph_cpu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    cpu_graphs = {}
    cpu_graphs["CPU Core power consumption"] = {MonitoringContextKeys.PowerConsumption: "Core"}
    cpu_graphs["Package power consumption"] = {MonitoringContextKeys.PowerConsumption: "package"}
    cpu_graphs["Core frequency"] = {MonitoringContextKeys.Freq: "Core"}
    cpu_graphs["Core IPC"] = {MonitoringContextKeys.IPC: "Core"}
    # Per-core metrics (filter "Core") are rendered twice: once for all the
    # cores of the system, once restricted to the cores that were pinned during
    # this benchmark job. Each rendering lands in its own subdirectory so the
    # two outputs never collide.
    pinned_core_names = bench.pinned_core_names()

    pinned_note = f"View limited to the pinned logical cores {bench.pinned_cpu_range()}"

    for graph_name in cpu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for metric, filter in cpu_graphs[graph_name].items():
            if filter == "Core":
                renderings = [("all_cores", None, None)]  # type: list
                if pinned_core_names:
                    renderings.append(("pinned_cores", pinned_core_names, pinned_note))
            else:
                # Non per-core metrics (e.g. package power) keep a single rendering.
                renderings = [(None, None, None)]
            for dir_suffix, names, title_note in renderings:
                for second_axis in [None, MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
                    rendered_graphs += generic_graph(
                        args,
                        output_dir,
                        bench,
                        metric,
                        graph_name,
                        second_axis,
                        filter=filter,
                        names=names,
                        dir_suffix=dir_suffix,
                        title_note=title_note,
                    )
                # Per-core metrics also get a steady-state distribution (violin + box).
                if filter == "Core":
                    rendered_graphs += cpu_distribution_graph(
                        args,
                        output_dir,
                        bench,
                        metric,
                        graph_name,
                        dir_suffix=dir_suffix,
                        names=names,
                        title_note=title_note,
                    )

    return rendered_graphs


def graph_cpu_numa(args, trace: Trace, bench_name: str, output_dir) -> int:
    """Render per-core CPU metrics aggregated by NUMA domain (one line per domain).

    Requires the NUMA topology in the trace; older traces without it are skipped.
    """
    numa_nodes = trace.get_numa_nodes()
    if not numa_nodes:
        print(f"{bench_name}: no NUMA metric present in trace file, skipping.")
        return 0
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    numa_graphs = {
        "Core frequency per NUMA domain": MonitoringContextKeys.Freq,
        "Core IPC per NUMA domain": MonitoringContextKeys.IPC,
        "CPU Core power consumption per NUMA domain": MonitoringContextKeys.PowerConsumption,
    }
    # Metrics that also get a per-domain x time heatmap next to their line graph.
    heatmap_metrics = {MonitoringContextKeys.Freq, MonitoringContextKeys.IPC}
    # Like the per-core graphs: one rendering averaging every core of each domain
    # (all_numa), and one restricted to the cores pinned during this job, grouped
    # by the domains those pinned cores belong to (pinned_numa).
    pinned_core_names = bench.pinned_core_names()
    # Each rendering is a dir suffix, the pinned-core filter, and a title note.
    renderings = [("all_numa", None, None)]  # type: list
    if pinned_core_names:
        pinned_note = f"View limited to the pinned logical cores {bench.pinned_cpu_range()}"
        renderings.append(("pinned_numa", pinned_core_names, pinned_note))

    for graph_name, metric in numa_graphs.items():
        for dir_suffix, pinned_cores, title_note in renderings:
            components = numa_aggregated_components(bench, metric, numa_nodes, pinned_cores)
            if not components:
                continue
            rendered_graphs += generic_graph(
                args,
                output_dir,
                bench,
                metric,
                graph_name,
                dir_suffix=dir_suffix,
                components=components,
                title_note=title_note,
            )
            # Companion heatmap: NUMA domain x time, color = per-domain value.
            if metric in heatmap_metrics:
                rendered_graphs += numa_performance_heatmap(
                    args,
                    output_dir,
                    bench,
                    metric,
                    graph_name,
                    numa_nodes,
                    dir_suffix=dir_suffix,
                    pinned_cores=pinned_cores,
                    title_note=title_note,
                )
            # Companion violin: one steady-state distribution per NUMA domain.
            rendered_graphs += numa_distribution_graph(
                args,
                output_dir,
                bench,
                metric,
                graph_name,
                numa_nodes,
                dir_suffix=dir_suffix,
                pinned_cores=pinned_cores,
                title_note=title_note,
            )
    return rendered_graphs


def graph_pdu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    pdu_graphs = {}
    pdu_graphs["PDU power reporting"] = {MonitoringContextKeys.PowerConsumption: "PDU"}
    for graph_name in pdu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for metric, filter in pdu_graphs[graph_name].items():
            for second_axis in [None, MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
                rendered_graphs += generic_graph(
                    args,
                    output_dir,
                    bench,
                    metric,
                    graph_name,
                    second_axis,
                    filter=filter,
                )

    return rendered_graphs


def graph_thermal(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    rendered_graphs += generic_graph(
        args, output_dir, trace.bench(bench_name), MonitoringContextKeys.Thermal, "Thermal"
    )
    return rendered_graphs


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="hwgraph",
        description="compare hwbench results and plot them",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(help="hwgraph sub-commands")

    parser_graph = subparsers.add_parser("graph", help="Generate graphs from trace files")
    parser_graph.add_argument(
        "--traces",
        type=valid_trace_file,
        nargs="+",
        help="""List of benchmarks to compare.
Syntax: <json_filename>:<logical_name>:<power_metric>
json_file    : a results.json output file from hwbench
logical_name : a name to represent the trace in the graph
               if omitted, it will be replaced by the system serial number
               'CPU' magic keyword implicit the use of CPU model as logical_name but must be unique over all trace files.
power_metric : the name of a power metric, from the monitoring, to be used for 'watts' and 'perf per watt' graphs; for example CPU.package or BMC.ServerInChassis.
               In order to know exeactly what metric names you can use for a given trace, use the "list" toplevel subcommand.
""",
        required=True,
    )
    parser_graph.add_argument("--no-env", help="Disable environmental graphs", action="store_false")
    parser_graph.add_argument("--no-scaling", help="Disable 'Performance scaling' graphs", action="store_false")
    parser_graph.add_argument("--no-versus", help="Disable 'max versus' graphs", action="store_false")
    parser_graph.add_argument("--no-stats", help="Disable stats", action="store_false")
    parser_graph.add_argument("--title", help="Title of the graph")
    parser_graph.add_argument("--dpi", help="Graph dpi", type=int, default="72")
    parser_graph.add_argument("--width", help="Graph width", type=int, default="1920")
    parser_graph.add_argument("--height", help="Graph height", type=int, default="1080")
    parser_graph.add_argument(
        "--events",
        type=valid_events,
        nargs="+",
        help="""List events that occurred during the benchmark.
Syntax: <event_name>:<start_time>:<duration>
event_name   : the name of an event
start_time   : the starting time of the event (in seconds)
duration     : duration of the event (in seconds)
""",
    )
    parser_graph.add_argument(
        "--format",
        help="Graph file format",
        type=str,
        choices=["svg", "png"],
        default="svg",
    )
    parser_graph.add_argument(
        "--engine",
        help="Select the matplotlib backend engine",
        choices=["pgf", "svg", "agg", "cairo"],
        default="cairo",
    )
    parser_graph.add_argument("--outdir", help="Name of the output directory", required=True)
    parser_graph.add_argument(
        "--same-chassis",
        help="All traces are from the same chassis",
        action="store_true",
    )
    parser_graph.add_argument(
        "--same-group",
        help="All traces are from the same group of servers",
        action="store_true",
    )
    parser_graph.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode",
    )

    parser_graph.add_argument(
        "--ignore-missing-datapoint",
        choices=["zero", "last"],
        default="",
        help="Replace a missing datapoint instead of stopping the rendering. Could be by a zero or the last known value.",
    )
    parser_graph.add_argument(
        "--jobs",
        "-j",
        help="Number of parallel worker processes for graph generation (default: number of CPUs)",
        type=int,
        default=os.cpu_count() // 2 or 1,
    )
    parser_graph.set_defaults(func=render_traces)

    parser_list = subparsers.add_parser("list", help="list monitoring metrics from a trace file")
    parser_list.add_argument(
        "--trace",
        type=str,
        help="""List power metrics of a trace file.""",
        required=True,
    )
    parser_list.set_defaults(func=list_metrics_in_trace)

    args = parser.parse_args(args=None if len(sys.argv) > 1 else ["--help"])

    # Call the appropriate sub command
    args.func(args)

    # Save the actual cmdline so it's easier to regenerate graph
    # Do not expose the actual hwbench path like /home/user/hwbench/...
    sys.argv[0] = "hwgraph"
    # Keep quotes from the argument list with shlex
    pathlib.Path(pathlib.Path(args.outdir).joinpath("cmdline")).write_text(
        " ".join(shlex.quote(arg) for arg in sys.argv)
    )


if __name__ == "__main__":
    main()
