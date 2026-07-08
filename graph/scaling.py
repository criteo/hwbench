from itertools import cycle
from statistics import stdev
from typing import Any  # noqa: F401

import numpy as np

from graph.graph import GRAPH_TYPES, Graph, statistics_in_label
from hwbench.bench.monitoring_structs import MonitoringContextKeys


def smp_scaling_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Render line graphs to compare performance scaling."""
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("smp_scaling")

    # We extract the skeleton from the first trace
    # This will give us the name of the engine module parameters and
    # the metrics we need to plot
    benches = args.traces[0].get_benches_by_job_per_emp(job)
    if args.verbose:
        print(f"SMP scaling: working on job '{job}' : {len(benches.keys())} engine_module_parameter to render")
    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for emp in benches:
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt_err = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock_err = {}  # type: dict[str, dict[str, Any]]
        # Same as above but restricted to the cores pinned during each benchmark
        aggregated_cpu_clock_pinned = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock_pinned_err = {}  # type: dict[str, dict[str, Any]]
        # IPC, same handling as cpu_clock (only rendered when the trace has IPC)
        aggregated_ipc = {}  # type: dict[str, dict[str, Any]]
        aggregated_ipc_err = {}  # type: dict[str, dict[str, Any]]
        aggregated_ipc_pinned = {}  # type: dict[str, dict[str, Any]]
        aggregated_ipc_pinned_err = {}  # type: dict[str, dict[str, Any]]
        # Whether at least one run of this sweep pinned cores (each run may pin a
        # different set), used to decide if the pinned-cores graph is relevant.
        any_pinned = False
        workers = {}  # type: dict[str, list]
        logical_core_per_worker = []
        perf_list, unit = benches[emp]["metrics"]

        # If we can't detect several bench on the same emp, it means there was no scaling
        if len(args.traces[0].get_benches_by_job_per_emp(job)[emp]["bench"]) == 1:
            print(f"SMP scaling: No scaling detected on job '{job}', skipping graph")
            continue

        # IPC is not always collected; only aggregate/render it when present.
        try:
            has_ipc = bool(benches[emp]["bench"][0].get_monitoring_metric(MonitoringContextKeys.IPC))
        except KeyError:
            has_ipc = False

        # For each metric we need to plot
        for perf in perf_list:
            if perf not in aggregated_perfs:
                aggregated_perfs[perf] = {}
                aggregated_perfs_watt[perf] = {}
                aggregated_watt[perf] = {}
                aggregated_watt_err[perf] = {}
                aggregated_cpu_clock[perf] = {}
                aggregated_cpu_clock_err[perf] = {}
                aggregated_cpu_clock_pinned[perf] = {}
                aggregated_cpu_clock_pinned_err[perf] = {}
                aggregated_ipc[perf] = {}
                aggregated_ipc_err[perf] = {}
                aggregated_ipc_pinned[perf] = {}
                aggregated_ipc_pinned_err[perf] = {}
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
                    if trace.get_name() not in aggregated_perfs[perf]:
                        aggregated_perfs[perf][trace.get_name()] = []
                        aggregated_perfs_watt[perf][trace.get_name()] = []
                        aggregated_watt[perf][trace.get_name()] = []
                        aggregated_watt_err[perf][trace.get_name()] = []
                        aggregated_cpu_clock[perf][trace.get_name()] = []
                        aggregated_cpu_clock_err[perf][trace.get_name()] = []
                        aggregated_cpu_clock_pinned[perf][trace.get_name()] = []
                        aggregated_cpu_clock_pinned_err[perf][trace.get_name()] = []
                        aggregated_ipc[perf][trace.get_name()] = []
                        aggregated_ipc_err[perf][trace.get_name()] = []
                        aggregated_ipc_pinned[perf][trace.get_name()] = []
                        aggregated_ipc_pinned_err[perf][trace.get_name()] = []

                    bench.add_perf(
                        perf,
                        traces_perf=aggregated_perfs[perf][trace.get_name()],
                        perf_watt=aggregated_perfs_watt[perf][trace.get_name()],
                        watt=aggregated_watt[perf][trace.get_name()],
                        watt_err=aggregated_watt_err[perf][trace.get_name()],
                        cpu_clock=aggregated_cpu_clock[perf][trace.get_name()],
                        cpu_clock_err=aggregated_cpu_clock_err[perf][trace.get_name()],
                    )

                    # Same cpu clock aggregation but averaging only the cores
                    # pinned during this benchmark (falls back to all cores when
                    # the benchmark has no pinning).
                    bench.add_perf(
                        cpu_clock=aggregated_cpu_clock_pinned[perf][trace.get_name()],
                        cpu_clock_err=aggregated_cpu_clock_pinned_err[perf][trace.get_name()],
                        cpu_clock_cores=bench.pinned_core_names(),
                    )
                    if has_ipc:
                        bench.add_perf(
                            ipc=aggregated_ipc[perf][trace.get_name()],
                            ipc_err=aggregated_ipc_err[perf][trace.get_name()],
                        )
                        bench.add_perf(
                            ipc=aggregated_ipc_pinned[perf][trace.get_name()],
                            ipc_err=aggregated_ipc_pinned_err[perf][trace.get_name()],
                            ipc_cores=bench.pinned_core_names(),
                        )
                    if bench.cpu_pin():
                        any_pinned = True

        # Let's render all graphs types (IPC only when the trace collected it)
        for graph_type in GRAPH_TYPES + (["cpu_ipc"] if has_ipc else []):
            # Let's render each performance graph
            graph_type_title = ""

            # for each performance metric we have to plot
            for perf in perf_list:
                clean_perf = perf.replace(" ", "").replace("/", "")
                y_label = unit
                # err_source is only set for graphs plotted with error bars.
                err_source = None
                # pinned_* are only set for per-core metrics (cpu_clock, ipc).
                pinned_y_source = None
                pinned_err_source = None
                if "perf_watt" in graph_type:
                    graph_type_title = f"SMP scaling {graph_type}: '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    y_label = f"{unit} per Watt"
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
                    y_source = aggregated_perfs_watt
                elif "watts" in graph_type:
                    graph_type_title = f"SMP scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    outfile = f"scaling_watt_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
                    y_label = "Watts"
                    y_source = aggregated_watt
                    err_source = aggregated_watt_err
                elif "cpu_clock" in graph_type:
                    graph_type_title = f"SMP scaling {graph_type}: {args.traces[0].get_metric_name()}"
                    outfile = f"scaling_cpu_clock_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
                    y_label = "Mhz"
                    y_source = aggregated_cpu_clock
                    err_source = aggregated_cpu_clock_err
                    pinned_y_source = aggregated_cpu_clock_pinned
                    pinned_err_source = aggregated_cpu_clock_pinned_err
                elif "ipc" in graph_type:
                    graph_type_title = f"SMP scaling {graph_type}: {bench.get_title_engine_name()}"
                    outfile = f"scaling_ipc_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
                    y_label = "IPC"
                    y_source = aggregated_ipc
                    err_source = aggregated_ipc_err
                    pinned_y_source = aggregated_ipc_pinned
                    pinned_err_source = aggregated_ipc_pinned_err
                else:
                    graph_type_title = f"SMP scaling {graph_type}: {bench.get_title_engine_name()}"
                    outfile = f"scaling_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
                    y_source = aggregated_perfs

                # The per-core metrics (cpu_clock, ipc) are rendered twice: once
                # averaging every system core, once averaging only the cores
                # pinned during each benchmark. Each variant is stored in its own
                # subdirectory so the two renderings never collide.
                if pinned_y_source is not None:
                    variants = [
                        ("all_cores", y_source, err_source, None),
                    ]  # type: list
                    # Only add the pinned-cores variant when at least one run of
                    # the sweep actually pinned cores (otherwise it duplicates
                    # the all-cores graph). Each scaling step pins its own set of
                    # cores, so we don't list a single global range here.
                    if any_pinned:
                        pinned_note = "View limited to the pinned cores of each scaling step"
                        variants.append(("pinned_cores", pinned_y_source, pinned_err_source, pinned_note))
                else:
                    variants = [(None, y_source, err_source, None)]

                for dir_suffix, v_y_source, v_err_source, note in variants:
                    outdir = temp_outdir.joinpath(graph_type)
                    if dir_suffix:
                        outdir = outdir.joinpath(dir_suffix)

                    title = f'{args.title}\n\n{graph_type_title} via "{job}" benchmark job\n\n Stressor: '
                    title += f"{bench.get_title_engine_name()} for {bench.duration()} seconds"
                    xlabel = "Workers"
                    # If we have a constant ratio between cores & workers, let's report them under the Xaxis
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
                        title_note=note,
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
                        y_serie = np.array(v_y_source[perf][trace_name])[order]
                        series_label = statistics_in_label(trace_name, y_serie)
                        # If we have an error distribution, let's use errorbars
                        if v_err_source is not None:
                            graph.get_ax().errorbar(
                                x_serie,
                                y_serie,
                                yerr=np.array(v_err_source[perf][trace_name]).T,
                                ecolor=e_color,
                                color=color_name,
                                capsize=4,
                                label=series_label,
                            )
                        else:
                            graph.get_ax().plot(
                                x_serie,
                                y_serie,
                                "",
                                color=color_name,
                                label=series_label,
                                marker="o",
                            )

                    graph.prepare_axes(8, 4)
                    graph.render()
                    rendered_graphs += 1

    return rendered_graphs
