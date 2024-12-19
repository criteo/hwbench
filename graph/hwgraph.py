#!/usr/bin/env python3
import argparse
import pathlib
import re
import sys
from typing import Any  # noqa: F401

try:
    from graph.common import fatal
    from graph.graph import init_matplotlib, generic_graph, yerr_graph
    from graph.individual import individual_graph
    from graph.scaling import scaling_graph
    from graph.chassis import graph_chassis
    from graph.trace import Trace
    from hwbench.bench.monitoring_structs import (
        FanContext,
        PowerCategories,
        PowerContext,
        Metrics,
    )
except ImportError as exc:
    print(exc)
    print(
        'Could not start hwgraph: did you make sure to also install the "graph" optional dependencies using `uv sync --extra graph` or `pip install hwbench[graph]`?'
    )
    sys.exit(1)


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
        print(f"Validation failure: {e}")
        raise e


def list_metrics_in_trace(args: argparse.Namespace):
    """List power metrics of a trace file"""
    Trace(args.trace).list_power_metrics()
    sys.exit(0)


def render_traces(args: argparse.Namespace):
    """Render the trace files passed in arguments"""
    rendered_graphs = 0
    init_matplotlib(args)
    output_dir = pathlib.Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compare_traces(args)
    rendered_graphs += graph_environment(args, output_dir)
    rendered_graphs += plot_graphs(args, output_dir)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


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
    for metric_name in ["BMC", "CPU", "PDU"]:
        metrics = bench.get_component(Metrics.MONITOR, metric_name)
        if metrics:
            for metric in metrics:
                # If a metric has no measure, let's ignore it
                if len(metrics[metric].get_samples()) == 0:
                    print(f"{bench_name}: No samples found in {metric_name}.{metric}, ignoring metric.")
                else:
                    rendered_graphs += yerr_graph(
                        args,
                        output_dir,
                        bench,
                        Metrics.MONITOR,
                        metrics[metric],
                        prefix=f"{metric_name}.",
                    )

    return rendered_graphs


def graph_fans(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    fans = bench.get_component(Metrics.FANS, FanContext.FAN)
    if not fans:
        print(f"{bench_name}: no fans")
        return rendered_graphs
    for second_axis in [Metrics.THERMAL, Metrics.POWER_CONSUMPTION]:
        rendered_graphs += generic_graph(args, output_dir, bench, Metrics.FANS, "Fans speed", second_axis)

    for fan in fans:
        rendered_graphs += yerr_graph(args, output_dir, bench, Metrics.FANS, fans[fan])

    return rendered_graphs


def graph_cpu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    cpu_graphs = {}
    cpu_graphs["CPU Core power consumption"] = {Metrics.POWER_CONSUMPTION: "Core"}
    cpu_graphs["Package power consumption"] = {Metrics.POWER_CONSUMPTION: "package"}
    cpu_graphs["Core frequency"] = {Metrics.FREQ: "Core"}
    for graph_name in cpu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for metric, filter in cpu_graphs[graph_name].items():
            for second_axis in [None, Metrics.THERMAL, Metrics.POWER_CONSUMPTION]:
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


def graph_pdu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    pdu_graphs = {}
    pdu_graphs["PDU power reporting"] = {Metrics.POWER_CONSUMPTION: "PDU"}
    for graph_name in pdu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for metric, filter in pdu_graphs[graph_name].items():
            for second_axis in [None, Metrics.THERMAL, Metrics.POWER_CONSUMPTION]:
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
    rendered_graphs += generic_graph(args, output_dir, trace.bench(bench_name), Metrics.THERMAL, str(Metrics.THERMAL))
    return rendered_graphs


def graph_environment(args, output_dir) -> int:
    rendered_graphs = 0
    # If user disabled the environmental graphs, return immediately
    if not args.no_env:
        print("environment: disabled by user")
        return rendered_graphs

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
                                Metrics.POWER_CONSUMPTION,
                                PowerContext.BMC,
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
                rendered_graphs += graph_chassis(args, bench_name, output_dir)
        else:
            print(error_message)

    for trace in args.traces:
        output_dir.joinpath(f"{trace.get_name()}").mkdir(parents=True, exist_ok=True)
        benches = trace.bench_list()
        print(f"environment: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})")
        for bench_name in sorted(benches):
            rendered_graphs += graph_monitoring_metrics(args, trace, bench_name, output_dir)
            rendered_graphs += graph_fans(args, trace, bench_name, output_dir)
            rendered_graphs += graph_cpu(args, trace, bench_name, output_dir)
            rendered_graphs += graph_pdu(args, trace, bench_name, output_dir)
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

    if not args.no_scaling:
        print("Scaling: disabled by user")
    else:
        # Let's generate the scaling graphs
        print(f"Scaling: rendering {len(jobs)} jobs")
        for job in jobs:
            rendered_graphs += scaling_graph(args, output_dir, job, traces_name)

    if not args.no_individual:
        print("Individual: disabled by user")
    else:
        # Let's generate the unitary comparing graphs
        print(f"Individual: rendering {len(jobs)} jobs")
        for job in jobs:
            rendered_graphs += individual_graph(args, output_dir, job, traces_name)

    return rendered_graphs


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
    parser_graph.add_argument("--no-scaling", help="Disable scaling graphs", action="store_false")
    parser_graph.add_argument("--no-individual", help="Disable individual graphs", action="store_false")
    parser_graph.add_argument("--title", help="Title of the graph")
    parser_graph.add_argument("--dpi", help="Graph dpi", type=int, default="72")
    parser_graph.add_argument("--width", help="Graph width", type=int, default="1920")
    parser_graph.add_argument("--height", help="Graph height", type=int, default="1080")
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


if __name__ == "__main__":
    main()
