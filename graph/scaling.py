from itertools import cycle
from statistics import stdev
from typing import Any  # noqa: F401

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea
from matplotlib.ticker import AutoMinorLocator

from graph.graph import (
    GRAPH_TYPES,
    Graph,
    get_max_value_string_length,
    numa_aggregated_components,
    numa_core_blocks,
    statistics_in_label,
)
from hwbench.bench.monitoring_structs import MonitoringContextKeys


def _bench_has_ipc(bench) -> bool:
    try:
        return bool(bench.get_monitoring_metric(MonitoringContextKeys.IPC))
    except KeyError:
        return False


def render_numa_delta_heatmaps(args, temp_outdir, job: str, emp: str) -> int:
    """Render per-NUMA-domain delta heatmaps comparing traces for one emp.

    The first trace is the reference; one heatmap is produced for each other
    trace (reference vs that trace), the compared trace name being part of the
    filename. Y = NUMA domains, X = scaling step (worker count), color = signed
    delta value(reference) - value(other) of the per-domain metric (white ~ no
    difference, red = reference higher, green = reference lower). Like the other
    scaling graphs, each metric is rendered for all_cores and, when the sweep
    pins cores, pinned_cores. Needs at least two traces exposing the NUMA
    topology.
    """
    if len(args.traces) < 2:
        return 0
    reference = args.traces[0]
    numa_nodes = reference.get_numa_nodes()
    if not numa_nodes:
        return 0
    reference_benches = reference.get_benches_by_job_per_emp(job)
    if emp not in reference_benches:
        return 0
    benches_ref = reference_benches[emp]["bench"]
    if not benches_ref:
        return 0

    engine = benches_ref[0].get_title_engine_name().replace(" ", "_")
    # all_cores always; pinned_cores when at least one run of the sweep pins cores.
    variants = [("all_cores", False, None)]  # type: list
    if any(bench.cpu_pin() for bench in benches_ref):
        variants.append(("pinned_cores", True, "View limited to the pinned cores of each scaling step"))

    rendered = 0
    # Compare the reference against every other trace, one heatmap set each.
    for other in args.traces[1:]:
        other_benches = other.get_benches_by_job_per_emp(job)
        if emp not in other_benches or not other_benches[emp]["bench"]:
            continue
        benches_other = other_benches[emp]["bench"]

        metrics = [("cpu_clock", MonitoringContextKeys.Freq, "MHz")]
        if _bench_has_ipc(benches_ref[0]) and _bench_has_ipc(benches_other[0]):
            metrics.append(("cpu_ipc", MonitoringContextKeys.IPC, "IPC"))

        pair = f"{reference.get_name()}_vs_{other.get_name()}".replace(" ", "_").replace("/", "_")
        for dirname, context, unit in metrics:
            for dir_suffix, use_pinned, note in variants:
                # Per trace: worker count -> {domain: mean metric value over the run}
                per_trace = []
                for benches in (benches_ref, benches_other):
                    values = {}  # type: dict[int, dict[int, float]]
                    for bench in benches:
                        pinned = bench.pinned_core_names() if use_pinned else None
                        domain_values = {
                            int(component.get_full_name().split()[1]): float(np.mean(component.get_mean()))
                            for component in numa_aggregated_components(bench, context, numa_nodes, pinned)
                        }
                        if domain_values:
                            values[bench.workers()] = domain_values
                    per_trace.append(values)
                values_ref, values_other = per_trace

                workers = sorted(set(values_ref) & set(values_other))
                domains = sorted({d for w in workers for d in set(values_ref[w]) & set(values_other[w])})
                if not workers or not domains:
                    continue

                matrix = np.full((len(domains), len(workers)), np.nan)
                for row, domain in enumerate(domains):
                    for col, worker in enumerate(workers):
                        ref = values_ref[worker].get(domain)
                        oth = values_other[worker].get(domain)
                        if ref is not None and oth is not None:
                            # Signed delta: reference minus other.
                            matrix[row, col] = ref - oth

                title = f'{args.title}\n\nSMP scaling NUMA {dirname} delta via "{job}" benchmark job\n'
                title += f"{unit} performance delta = ({reference.get_name()} (reference) - {other.get_name()})"
                # Colour legend rendered as a caption below the graph (see below),
                # with the "red" and "green" words drawn in their respective colour.
                # No segment starts/ends with a space (TextArea drops edge spaces,
                # which made the coloured words collide); word gaps come from the
                # HPacker sep below instead.
                caption_tail = f"{other.get_name()} is higher than reference, white: no difference"
                if use_pinned:
                    caption_tail += ", black: unused NUMA node during benchmark"
                caption_segments = [
                    ("red:", "red"),
                    (f"{other.get_name()} is lower than reference, ", "black"),
                    (" green:", "green"),
                    (caption_tail, "black"),
                ]
                graph = Graph(
                    args,
                    title,
                    "Workers (scaling step)",
                    "NUMA domain",
                    temp_outdir.joinpath(dirname, dir_suffix),
                    f"scaling_{dirname}_numa_delta_{pair}_{engine}",
                    title_note=note,
                )
                ax = graph.get_ax()
                # Diverging map centered on 0: positive delta -> red, negative -> green.
                finite = matrix[np.isfinite(matrix)]
                bound = float(np.abs(finite).max()) if finite.size else 1.0
                bound = bound or 1.0
                cmap = LinearSegmentedColormap.from_list("numa_delta", ["green", "white", "red"])
                # Missing data: black on the pinned view (domain not pinned at that
                # step), light grey otherwise, so it is not mistaken for a zero delta.
                cmap.set_bad("black" if use_pinned else "0.85")
                image = ax.imshow(
                    np.ma.masked_invalid(matrix),
                    aspect="auto",
                    cmap=cmap,
                    norm=Normalize(-bound, bound),
                    interpolation="nearest",
                )
                graph.fig.colorbar(
                    image,
                    ax=ax,
                    fraction=0.046,
                    pad=0.04,
                    label=f"{reference.get_name()} - {other.get_name()} ({unit})",
                )
                ax.set_xticks(range(len(workers)))
                ax.set_xticklabels(workers)
                ax.set_yticks(range(len(domains)))
                ax.set_yticklabels([f"NUMA {domain}" for domain in domains])

                # Left box listing each domain's cores (condensed). For the pinned
                # variant, the union of cores pinned across the sweep per domain.
                if use_pinned:
                    pinned_union = set()  # type: set
                    for bench in benches_ref:
                        pinned_union |= {int(name.split("_")[1]) for name in (bench.pinned_core_names() or set())}
                    cores_by_domain = {d: [c for c in numa_nodes[d] if c in pinned_union] for d in domains}
                else:
                    cores_by_domain = {d: numa_nodes[d] for d in domains}
                node_width = max((len(str(domain)) for domain in domains), default=1)
                legend_labels = [
                    f"NUMA {domain:>{node_width}}; {numa_core_blocks(cores_by_domain[domain])}" for domain in domains
                ]
                handles = [Line2D([], [], linestyle="none") for _ in legend_labels]
                legend = ax.legend(
                    handles,
                    legend_labels,
                    loc="upper right",
                    # Enough room from the Y-axis so 3-digit core numbers don't collide with it.
                    bbox_to_anchor=(-0.1, 1),
                    title="NUMA domain [cores]",
                    handlelength=0,
                    handletextpad=0,
                )
                # Colour legend caption below the graph: one TextArea per segment
                # so "red"/"green" can be drawn in their own colour. A proportional
                # font is used because the cairo backend mismeasures monospace text
                # width, which would make the HPacker segments overlap.
                caption = HPacker(
                    children=[
                        TextArea(text, textprops=dict(color=color, fontfamily="sans-serif"))
                        for text, color in caption_segments
                    ],
                    align="baseline",
                    pad=0,
                    # A gap the width of a space between segments (edge spaces are dropped).
                    sep=3,
                )
                ax.add_artist(
                    AnchoredOffsetbox(
                        loc="upper center",
                        child=caption,
                        pad=0,
                        frameon=False,
                        bbox_to_anchor=(0.5, -0.16),
                        bbox_transform=ax.transAxes,
                    )
                )
                graph.needs_legend = False
                graph.render(extra_legend=legend)
                rendered += 1
    return rendered


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
                    outfile = f"scaling_cpu_ipc_{clean_perf}_{bench.get_title_engine_name().replace(' ', '_')}"
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
                    # Pad the trace name and the values to a common width so the
                    # per-trace legend table stays aligned even when trace names
                    # (or values) have different lengths.
                    max_title_length = max((len(trace_name) for trace_name in v_y_source[perf]), default=0)
                    max_value_length = max(
                        (
                            get_max_value_string_length(np.array(v_y_source[perf][trace_name]))
                            for trace_name in v_y_source[perf]
                        ),
                        default=0,
                    )
                    # Traces are not ordered by growing cpu cores count
                    # We need to prepare the x_serie to be sorted this way
                    # The y_serie depends on the graph type
                    for trace_name, color_name, e_color in zip(aggregated_perfs[perf], colors, cycle(e_colors)):
                        # Each trace can have different numbers of workers based on the hardware setup
                        # So let's consider the list of x values per trace.
                        order = np.argsort(workers[trace_name])
                        x_serie = np.array(workers[trace_name])[order]
                        y_serie = np.array(v_y_source[perf][trace_name])[order]
                        series_label = statistics_in_label(trace_name, y_serie, max_title_length, max_value_length)
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
                    # Add a midline between Y ticks to ease value reading (a bit more
                    # visible than the default minor grid, but still lighter than the major one).
                    graph.get_ax().yaxis.set_minor_locator(AutoMinorLocator(2))
                    graph.get_ax().grid(which="minor", axis="y", linewidth=0.6, linestyle="dashed", color="0.6")
                    graph.render()
                    rendered_graphs += 1

        # Per-NUMA-domain delta heatmap comparing the two traces (reference vs other).
        rendered_graphs += render_numa_delta_heatmaps(args, temp_outdir, job, emp)

    return rendered_graphs
