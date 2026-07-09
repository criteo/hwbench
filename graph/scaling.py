from __future__ import annotations

from itertools import cycle
from statistics import stdev
from typing import Any  # noqa: F401

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea
from matplotlib.patches import Patch
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


def render_scaling_distributions(args, temp_outdir, job: str, emp: str, has_ipc: bool) -> int:
    """Render the per-core metric distribution across the scaling steps.

    For each trace and each per-core metric (frequency, IPC and per-core power),
    one graph shows how the core-to-core distribution evolves as the sweep grows:
    X = worker count (one violin + box per scaling step, evenly spaced), Y = the
    metric. The violin shows the density across cores, the box the median (red),
    mean (green dashed), quartiles and outliers.

    Where the scaling line graphs plot a single averaged value per step, these
    expose the spread hidden behind that average -- e.g. cores starting to
    throttle or diverge only past a given worker count. Like the other per-core
    scaling graphs they are rendered for all_cores and, when the sweep pins
    cores, pinned_cores, and the Y axis is autoscaled (a distribution is
    unreadable squished against a zero baseline).
    """
    metrics = [
        ("cpu_clock", MonitoringContextKeys.Freq, "Mhz", "Core frequency"),
    ]  # type: list
    if has_ipc:
        metrics.append(("cpu_ipc", MonitoringContextKeys.IPC, "IPC", "Core IPC"))
    metrics.append(("cpu_core_power", MonitoringContextKeys.PowerConsumption, None, "CPU Core power consumption"))

    rendered = 0
    for trace in args.traces:
        trace_benches = trace.get_benches_by_job_per_emp(job)
        if emp not in trace_benches or not trace_benches[emp]["bench"]:
            continue
        benches = trace_benches[emp]["bench"]
        engine = benches[0].get_title_engine_name().replace(" ", "_")
        trace_slug = trace.get_name().replace(" ", "_").replace("/", "_")
        # all_cores always; pinned_cores when at least one run of the sweep pins cores.
        variants = [("all_cores", False, None)]  # type: list
        if any(bench.cpu_pin() for bench in benches):
            variants.append(("pinned_cores", True, "View limited to the pinned cores of each scaling step"))

        for dirname, context, unit, item_title in metrics:
            for dir_suffix, use_pinned, note in variants:
                data = []  # type: list
                labels = []  # type: list
                metric_unit = ""
                for bench in sorted(benches, key=lambda b: b.workers()):
                    names = bench.pinned_core_names() if use_pinned else None
                    components = bench.get_all_metrics(context, "Core", names)
                    if not components:
                        continue
                    data.append([float(np.mean(component.get_mean())) for component in components])
                    labels.append(bench.workers())
                    metric_unit = bench.get_metric_unit(context)
                if not data:
                    continue

                title = f'{args.title}\n\n{item_title} per-core distribution scaling via "{job}" benchmark job\n\n Stressor: '
                title += f"{benches[0].get_title_engine_name()} for {benches[0].duration()} seconds"
                graph = Graph(
                    args,
                    title,
                    "Workers (scaling step)",
                    unit or metric_unit,
                    temp_outdir.joinpath(dirname, dir_suffix),
                    f"scaling_{dirname}_distribution_{trace_slug}_{engine}",
                    square=True,
                    show_source_file=trace,
                    title_note=note,
                )
                ax = graph.get_ax()
                positions = list(range(1, len(data) + 1))
                parts = ax.violinplot(data, positions=positions, widths=0.7, showextrema=False)
                for body in parts["bodies"]:
                    body.set_facecolor("tab:blue")
                    body.set_alpha(0.25)
                ax.boxplot(
                    data,
                    positions=positions,
                    widths=0.15,
                    showmeans=True,
                    meanline=True,
                    medianprops=dict(color="tab:red"),
                    meanprops=dict(color="tab:green", linestyle="--"),
                    flierprops=dict(marker=".", markersize=3, alpha=0.4),
                )
                ax.set_xticks(positions)
                ax.set_xticklabels(labels)
                ax.grid(which="major", axis="y", linewidth=0.6, linestyle="dashed", color="0.7")
                legend = ax.legend(
                    handles=[
                        Line2D([], [], color="tab:red", label="median"),
                        Line2D([], [], color="tab:green", linestyle="--", label="mean"),
                    ],
                    loc="upper right",
                    fontsize=8,
                )
                graph.needs_legend = False
                graph.render(extra_legend=legend)
                rendered += 1
    return rendered


# Colours cycled across NUMA domains in the render_numa_scaling_* graphs below, so
# each domain keeps the same colour everywhere it appears. tab20 gives 20 distinct
# colours, enough for every domain count seen on real systems so far; it only wraps
# (and two domains start sharing a colour) past that.
_NUMA_DOMAIN_COLORS = [matplotlib.colormaps["tab20"](i) for i in range(20)]

# Pale background washes used by render_numa_scaling_ridgelines to mark which CPU
# package each NUMA domain belongs to, cycled per package. Kept very light so they
# stay subordinate to the (much more saturated) per-domain ridge colours.
_NUMA_PACKAGE_BAND_COLORS = ["#eaf1fb", "#fbf1e2", "#eaf7ee", "#f6eef8"]


# hwbench does not record which package a NUMA domain sits on, but same-package
# domains are always much closer to each other than cross-package ones (see the
# sample matrices in hwbench/environment/numa.py: ~10-12 within a package, 32+
# across). 20 sits comfortably between the two tiers.
_NUMA_SAME_PACKAGE_DISTANCE = 20


def _numa_domains_by_package(numa_nodes: dict, numa_distances: dict) -> dict | None:
    """Group NUMA domains into CPU packages, from the distance matrix.

    Connects domains whose mutual distance is below _NUMA_SAME_PACKAGE_DISTANCE
    (union-find) and returns {domain: package index}. Returns None when there is
    nothing to distinguish (everything lands in one group, e.g. a single socket)
    or the matrix is missing/incomplete.
    """
    if len(numa_nodes) <= 1 or not numa_distances:
        return None
    domains = sorted(numa_nodes)
    if not all(d in numa_distances and len(numa_distances[d]) > max(domains) for d in domains):
        return None

    parent = {d: d for d in domains}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for d in domains:
        for o in domains:
            if d != o and numa_distances[d][o] < _NUMA_SAME_PACKAGE_DISTANCE:
                root_d, root_o = find(d), find(o)
                if root_d != root_o:
                    parent[root_d] = root_o

    groups: dict = {}
    for d in domains:
        groups.setdefault(find(d), []).append(d)

    if len(groups) <= 1:
        return None
    ordered_groups = sorted(groups.values(), key=min)
    return {d: package for package, group in enumerate(ordered_groups) for d in group}


def _numa_scaling_metrics(has_ipc: bool) -> list:
    """Metrics rendered by the render_numa_scaling_* graphs below."""
    metrics = [
        ("cpu_clock", MonitoringContextKeys.Freq, "Mhz", "Core frequency per NUMA domain"),
    ]  # type: list
    if has_ipc:
        metrics.append(("cpu_ipc", MonitoringContextKeys.IPC, "IPC", "Core IPC per NUMA domain"))
    metrics.append(
        (
            "cpu_core_power",
            MonitoringContextKeys.PowerConsumption,
            None,
            "CPU Core power consumption per NUMA domain",
        )
    )
    return metrics


def _numa_scaling_variants(benches: list) -> list:
    """all_numa always; pinned_numa when at least one run of the sweep pins cores."""
    variants = [("all_numa", False, None)]  # type: list
    if any(bench.cpu_pin() for bench in benches):
        variants.append(("pinned_numa", True, "View limited to the pinned logical cores of each scaling step"))
    return variants


def _collect_numa_step_domain_values(benches: list, context, numa_nodes, use_pinned: bool) -> dict:
    """Return {worker count: {domain: [per-core steady-state values]}} for one metric/variant."""
    per_step = {}  # type: dict[int, dict[int, list]]
    for bench in benches:
        pinned = bench.pinned_core_names() if use_pinned else None
        step_domains = {}
        for node in sorted(numa_nodes):
            core_names = {f"Core_{cpu}" for cpu in numa_nodes[node]}
            if pinned is not None:
                core_names &= pinned
            if not core_names:
                continue
            cores = bench.get_all_metrics(context, names=core_names)
            if not cores:
                continue
            step_domains[node] = [float(np.mean(core.get_mean())) for core in cores]
        if step_domains:
            per_step[bench.workers()] = step_domains
    return per_step


def _numa_scaling_cores_by_domain(numa_nodes, domains: list, benches: list, use_pinned: bool) -> dict:
    """{domain: [cpus]}, restricted to the union of cores pinned across the sweep on the pinned view."""
    pinned_union = None  # type: set | None
    if use_pinned:
        pinned_union = set()
        for bench in benches:
            pinned_union |= {int(name.split("_")[1]) for name in (bench.pinned_core_names() or set())}
    cores_by_domain = {}
    for node in domains:
        cpus = numa_nodes[node]
        if pinned_union is not None:
            cpus = [cpu for cpu in cpus if cpu in pinned_union]
        cores_by_domain[node] = cpus
    return cores_by_domain


def _save_standalone_figure(args, fig, output_dir, filename: str) -> None:
    """Save a figure built without the Graph wrapper (used by grid/multi-axes graphs).

    Mirrors Graph.render()'s save call so standalone figures match the rest of
    hwgraph's output (same directory creation, format, dpi and tight bbox).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        f"{output_dir}/{filename}.{args.format}",
        format=args.format,
        dpi=args.dpi,
        bbox_inches="tight",
        pad_inches=1,
    )
    fig.clear()
    plt.close(fig)


def _gaussian_kde_curve(values: list, sample_points: np.ndarray) -> np.ndarray:
    """Scipy-free Gaussian KDE (Silverman's rule-of-thumb bandwidth), unnormalized."""
    values_arr = np.asarray(values, dtype=float)
    std = float(np.std(values_arr))
    bandwidth = 1.06 * std * len(values_arr) ** (-1 / 5) if std > 0 else 1.0
    bandwidth = max(bandwidth, 1e-3)
    diffs = (sample_points[:, None] - values_arr[None, :]) / bandwidth
    return np.exp(-0.5 * diffs**2).sum(axis=1)


# render_numa_scaling_ridgelines lays out one panel per step, _RIDGELINE_MAX_COLS
# per row, so the grid (and the figure) grows taller as a sweep has more steps.
# The header/footer are reserved as a constant number of INCHES rather than a
# fraction of the figure, so they keep the same size and never shrink to
# nothing (or balloon) as the number of rows changes.
_RIDGELINE_PANEL_WIDTH = 3.0
_RIDGELINE_PANEL_HEIGHT = 3.3
_RIDGELINE_MAX_COLS = 5
_RIDGELINE_SUPTITLE_INSET = 0.05  # inches from the top edge to the suptitle anchor
_RIDGELINE_NOTE_INSET = 1.3  # inches from the top edge to the note (when present)
_RIDGELINE_HEADER_INCHES = 1.6  # reserved header height: title only
_RIDGELINE_HEADER_INCHES_NOTE = 2.0  # reserved header height: title + note
_RIDGELINE_FOOTER_INCHES = 0.5  # reserved footer height: source caption
_RIDGELINE_FOOTER_INCHES_PACKAGE = 0.85  # reserved footer height: source caption + package legend
_RIDGELINE_CAPTION_INSET = 0.08  # inches from the bottom edge to the source caption
_RIDGELINE_PACKAGE_LEGEND_INSET = 0.4  # inches from the bottom edge to the package legend


def render_numa_scaling_ridgelines(args, temp_outdir, job: str, emp: str, has_ipc: bool) -> int:
    """Render the per-NUMA-domain metric distribution at every scaling step.

    For each trace and each per-NUMA metric (frequency, IPC and per-core
    power, aggregated by domain), one graph lays out one ridgeline panel per
    scaling step -- every step, not a sample -- in a grid: each panel is a
    stacked density (ridgeline) per NUMA domain, preserving the full
    distribution shape (skew, bimodality) that a single averaged value would
    flatten.

    Like the other per-domain scaling graphs, rendered for all_numa (every
    core of each domain) and, when the sweep pins cores, pinned_numa. Needs
    the NUMA topology in each trace; older traces without it are skipped.
    """
    rendered = 0
    for trace in args.traces:
        # Topology is per-host: read it from this trace, not a shared reference,
        # so hosts with different NUMA-node counts each render their own domains.
        numa_nodes = trace.get_numa_nodes()
        if not numa_nodes:
            continue
        # Best-effort: which package each domain sits on, so multi-socket systems get a
        # background wash marking the boundary; None on a single socket or when the
        # distance matrix doesn't cleanly cluster (older trace, unexpected encoding).
        domain_package = _numa_domains_by_package(numa_nodes, trace.get_numa_distances())

        trace_benches = trace.get_benches_by_job_per_emp(job)
        if emp not in trace_benches or not trace_benches[emp]["bench"]:
            continue
        benches = sorted(trace_benches[emp]["bench"], key=lambda b: b.workers())
        engine = benches[0].get_title_engine_name().replace(" ", "_")
        trace_slug = trace.get_name().replace(" ", "_").replace("/", "_")
        variants = _numa_scaling_variants(benches)

        for dirname, context, unit, item_title in _numa_scaling_metrics(has_ipc):
            for dir_suffix, use_pinned, note in variants:
                per_step = _collect_numa_step_domain_values(benches, context, numa_nodes, use_pinned)
                if not per_step:
                    continue
                steps = sorted(per_step)
                domains = sorted({node for step_domains in per_step.values() for node in step_domains})
                metric_unit = unit or benches[0].get_metric_unit(context)
                cores_by_domain = _numa_scaling_cores_by_domain(numa_nodes, domains, benches, use_pinned)
                domain_color = {
                    node: _NUMA_DOMAIN_COLORS[i % len(_NUMA_DOMAIN_COLORS)] for i, node in enumerate(domains)
                }

                all_values = [
                    v for step_domains in per_step.values() for values in step_domains.values() for v in values
                ]
                pad = (max(all_values) - min(all_values)) * 0.05 or 1
                yy = np.linspace(min(all_values) - pad, max(all_values) + pad, 200)

                # Every step gets a panel -- no sampling -- laid out as a grid so the
                # figure grows in rows rather than becoming arbitrarily wide.
                cols = min(_RIDGELINE_MAX_COLS, len(steps))
                rows = -(-len(steps) // cols)  # ceil division
                header_inches = _RIDGELINE_HEADER_INCHES_NOTE if note else _RIDGELINE_HEADER_INCHES
                footer_inches = (
                    _RIDGELINE_FOOTER_INCHES_PACKAGE if domain_package is not None else _RIDGELINE_FOOTER_INCHES
                )
                fig_width = _RIDGELINE_PANEL_WIDTH * cols
                fig_height = _RIDGELINE_PANEL_HEIGHT * rows + header_inches + footer_inches
                fig, axes = plt.subplots(rows, cols, figsize=(fig_width, fig_height), sharey=True, squeeze=False)
                flat_axes = axes.flatten()

                for ax, step in zip(flat_axes, steps):
                    step_domains = per_step[step]
                    present = [node for node in domains if node in step_domains]
                    offsets = np.arange(len(present)) * 1.1

                    # Background wash per CPU package, drawn first so the ridges sit on top.
                    if domain_package is not None:
                        package_offsets: dict = {}
                        for offset, node in zip(offsets, present):
                            package_offsets.setdefault(domain_package[node], []).append(offset)
                        for package, offs in package_offsets.items():
                            ax.axvspan(
                                min(offs) - 0.55,
                                max(offs) + 0.55,
                                color=_NUMA_PACKAGE_BAND_COLORS[package % len(_NUMA_PACKAGE_BAND_COLORS)],
                                zorder=0,
                            )

                    for offset, node in zip(offsets, present):
                        density = _gaussian_kde_curve(step_domains[node], yy)
                        peak = density.max()
                        if peak > 0:
                            density = density / peak
                        ax.fill_betweenx(yy, offset, offset + density, color=domain_color[node], alpha=0.8, zorder=2)
                        ax.plot(offset + density, yy, color="black", linewidth=0.5, zorder=2)
                    ax.set_xticks(offsets)
                    ax.set_xticklabels([f"N{node}" for node in present], rotation=90, fontsize=6)
                    ax.set_title(f"{step} workers", fontsize=9)
                    ax.set_xlim(-0.3, (offsets[-1] if len(offsets) else 0) + 1.3)
                    ax.grid(which="major", axis="y", linewidth=0.4, linestyle="dashed", color="0.85", zorder=1)
                for ax in flat_axes[len(steps) :]:
                    ax.axis("off")
                # Y label on the leftmost panel of every row (sharey makes the scale common).
                for row in range(rows):
                    flat_axes[row * cols].set_ylabel(metric_unit)

                node_width = max((len(str(node)) for node in domains), default=1)
                handles = [Line2D([], [], color=domain_color[node], linewidth=6) for node in domains]
                labels = [
                    f"NUMA {node:>{node_width}}"
                    + (f" (pkg {domain_package[node]})" if domain_package is not None else "")
                    + f": {numa_core_blocks(cores_by_domain[node])}"
                    for node in domains
                ]
                fig.legend(
                    handles,
                    labels,
                    loc="center left",
                    bbox_to_anchor=(1.0, 0.5),
                    title="NUMA domain [cores]",
                    fontsize=8,
                )
                # Separate legend explaining the background wash colour, centered below the
                # grid (fig.legend keeps every call as its own legend, unlike ax.legend which
                # replaces the last one).
                if domain_package is not None:
                    package_count = len(set(domain_package.values()))
                    package_handles = [
                        Patch(
                            facecolor=_NUMA_PACKAGE_BAND_COLORS[package % len(_NUMA_PACKAGE_BAND_COLORS)],
                            edgecolor="0.6",
                        )
                        for package in range(package_count)
                    ]
                    package_labels = [f"CPU package {package}" for package in range(package_count)]
                    fig.legend(
                        package_handles,
                        package_labels,
                        loc="lower center",
                        bbox_to_anchor=(0.5, _RIDGELINE_PACKAGE_LEGEND_INSET / fig_height),
                        ncol=package_count,
                        fontsize=8,
                    )

                title = f'{args.title}\n\n{item_title} distribution scaling via "{job}" benchmark job\n\n Stressor: '
                title += f"{benches[0].get_title_engine_name()} for {benches[0].duration()} seconds"
                fig.suptitle(title, fontsize=11, y=1 - _RIDGELINE_SUPTITLE_INSET / fig_height)
                if note:
                    fig.text(
                        0.5,
                        1 - _RIDGELINE_NOTE_INSET / fig_height,
                        note,
                        ha="center",
                        color="darkred",
                        fontweight="bold",
                        fontsize=10,
                    )
                fig.text(
                    0.01,
                    _RIDGELINE_CAPTION_INSET / fig_height,
                    f"data plotted from {trace.get_filename()}",
                    fontsize=8,
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.6),
                )
                fig.tight_layout(
                    rect=(
                        0.02,
                        footer_inches / fig_height,
                        1,
                        1 - header_inches / fig_height,
                    )
                )

                _save_standalone_figure(
                    args,
                    fig,
                    temp_outdir.joinpath(dirname, dir_suffix),
                    f"scaling_{dirname}_numa_ridgeline_{trace_slug}_{engine}",
                )
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

        # Per-core distribution (violin + box) across the scaling steps.
        rendered_graphs += render_scaling_distributions(args, temp_outdir, job, emp, has_ipc)

        # Per-NUMA-domain distribution across the scaling steps: a ridgeline grid,
        # one panel per step, one density per domain within each panel.
        rendered_graphs += render_numa_scaling_ridgelines(args, temp_outdir, job, emp, has_ipc)

    return rendered_graphs
