import matplotlib.pyplot as plt
import numpy as np
from typing import Any  # noqa: F401
from graph.graph import Graph, GRAPH_TYPES


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
                        aggregated_perfs_watt[perf][bench.workers()] = [0] * len(traces_name)
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
                        max_perfs_watt[perf][index] = aggregated_perfs_watt[perf][bench.workers()][index]
                        max_watt[perf][index] = aggregated_watt[perf][bench.workers()][index]
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
                # If the benchmark has multiple performance results, let's put them in a specific directory
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
                    graph_type_title = f"Individual {graph_type}: {args.traces[0].get_metric_name()}"
                    graph_type_title += ": Lower is better"
                    y_label = "Watts"
                    y_source = aggregated_watt
                    y_max = max_watt
                else:
                    graph_type_title = f"Individual {graph_type}: {bench.get_title_engine_name()}"
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
                for max_perf_type in ["max_perf_total", "max_perf_per_core"]:
                    title = f'{args.title}\n\n{graph_type_title} during "{job}" benchmark\n'
                    if max_perf_type == "max_perf_per_core":
                        title += f"\nPer core maximum performance during {bench.duration()} seconds"
                        y_max_per_core = [0] * len(y_max[perf])
                        # Let's compute the performance per physical core
                        for ymax_nb in range(len(y_max[perf])):
                            y_max_per_core[ymax_nb] = y_max[perf][ymax_nb] / args.traces[ymax_nb].get_physical_cores()
                        y_serie = np.array(y_max_per_core)
                    else:
                        title += f"\nProduct maximum performance during {bench.duration()} seconds"
                        y_serie = np.array(y_max[perf])

                    graph = Graph(
                        args,
                        title,
                        "",
                        y_label,
                        outdir,
                        f"{max_perf_type}_{outfile}{graph_type}_{clean_perf}",
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
                            bar_labels[trace_nb] += f"\n{max_workers[perf][trace_nb]} workers"
                    graph.get_ax().axes.xaxis.set_ticks(traces_name)
                    graph.get_ax().set_xticklabels(bar_labels)

                    graph.prepare_axes(legend=False)
                    graph.render()
                    rendered_graphs += 1

    return rendered_graphs
