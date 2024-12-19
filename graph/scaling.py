import numpy as np
from itertools import cycle
from statistics import stdev
from typing import Any  # noqa: F401
from graph.graph import Graph, GRAPH_TYPES


def scaling_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Render line graphs to compare performance scaling."""
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("scaling")

    # We extract the skeleton from the first trace
    # This will give us the name of the engine module parameters and
    # the metrics we need to plot
    benches = args.traces[0].get_benches_by_job_per_emp(job)
    if args.verbose:
        print(f"Scaling: working on job '{job}' : {len(benches.keys())} engine_module_parameter to render")
    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for emp in benches.keys():
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt_err = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock_err = {}  # type: dict[str, dict[str, Any]]
        workers = {}  # type: dict[str, list]
        logical_core_per_worker = []
        perf_list, unit = benches[emp]["metrics"]

        # If we can't detect several bench on the same emp, it means there was no scaling
        if len(args.traces[0].get_benches_by_job_per_emp(job)[emp]["bench"]) == 1:
            print(f"Scaling: No scaling detected on job '{job}', skipping graph")
            continue

        # For each metric we need to plot
        for perf in perf_list:
            if perf not in aggregated_perfs.keys():
                aggregated_perfs[perf] = {}
                aggregated_perfs_watt[perf] = {}
                aggregated_watt[perf] = {}
                aggregated_watt_err[perf] = {}
                aggregated_cpu_clock[perf] = {}
                aggregated_cpu_clock_err[perf] = {}
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
                        aggregated_watt_err[perf][trace.get_name()] = []
                        aggregated_cpu_clock[perf][trace.get_name()] = []
                        aggregated_cpu_clock_err[perf][trace.get_name()] = []

                    bench.add_perf(
                        perf,
                        traces_perf=aggregated_perfs[perf][trace.get_name()],
                        perf_watt=aggregated_perfs_watt[perf][trace.get_name()],
                        watt=aggregated_watt[perf][trace.get_name()],
                        watt_err=aggregated_watt_err[perf][trace.get_name()],
                        cpu_clock=aggregated_cpu_clock[perf][trace.get_name()],
                        cpu_clock_err=aggregated_cpu_clock_err[perf][trace.get_name()],
                    )

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
                    graph_type_title = (
                        f"Scaling {graph_type}: '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    )
                    y_label = f"{unit} per Watt"
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}"
                    y_source = aggregated_perfs_watt
                elif "watts" in graph_type:
                    graph_type_title = f"Scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}"
                    y_label = "Watts"
                    y_source = aggregated_watt
                elif "cpu_clock" in graph_type:
                    graph_type_title = f"Scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    outfile = f"scaling_cpu_clock_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}"
                    y_label = "Mhz"
                    y_source = aggregated_cpu_clock
                else:
                    graph_type_title = f"Scaling {graph_type}: {bench.get_title_engine_name()}"
                    outfile = f"scaling_{clean_perf}_{bench.get_title_engine_name().replace(' ','_')}"
                    y_source = aggregated_perfs

                title = f'{args.title}\n\n{graph_type_title} via "{job}" benchmark job\n' f"\n Stressor: "
                title += f"{bench.get_title_engine_name()} for {bench.duration()} seconds"
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

                # Let's defined colors used during the rendering
                # As we use error bars, let's ensure colors are readable with the error color.
                colors = [
                    "tab:blue",
                    "tab:purple",
                    "tab:green",
                    "peru",
                    "slategrey",
                ]
                e_colors = [
                    "darkblue",
                    "darkmagenta",
                    "darkgreen",
                    "tab:brown",
                    "tab:grey",
                ]
                # Traces are not ordered by growing cpu cores count
                # We need to prepare the x_serie to be sorted this way
                # The y_serie depends on the graph type
                for trace_name, color_name, e_color in zip(aggregated_perfs[perf], colors, cycle(e_colors)):
                    # Each trace can have different numbers of workers based on the hardware setup
                    # So let's consider the list of x values per trace.
                    order = np.argsort(workers[trace_name])
                    x_serie = np.array(workers[trace_name])[order]
                    y_serie = np.array(y_source[perf][trace_name])[order]
                    # If we plot the power consumption, let's use errorbars
                    if y_source == aggregated_watt:
                        graph.get_ax().errorbar(
                            x_serie,
                            y_serie,
                            yerr=np.array(aggregated_watt_err[perf][trace_name]).T,
                            ecolor=e_color,
                            color=color_name,
                            capsize=4,
                            label=trace_name,
                        )
                    elif y_source == aggregated_cpu_clock:
                        graph.get_ax().errorbar(
                            x_serie,
                            y_serie,
                            yerr=np.array(aggregated_cpu_clock_err[perf][trace_name]).T,
                            ecolor=e_color,
                            color=color_name,
                            capsize=4,
                            label=trace_name,
                        )
                    else:
                        graph.get_ax().plot(
                            x_serie,
                            y_serie,
                            "",
                            color=color_name,
                            label=trace_name,
                            marker="o",
                        )

                graph.prepare_axes(8, 4)
                graph.render()
                rendered_graphs += 1

    return rendered_graphs
