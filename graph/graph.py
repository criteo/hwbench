from __future__ import annotations

from itertools import cycle

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.pylab import Axes
from matplotlib.ticker import AutoMinorLocator, FuncFormatter, MultipleLocator

from graph.common import context_header, fatal
from graph.trace import Bench, gpu_description
from hwbench.bench.engine import Resource
from hwbench.bench.monitoring_structs import CORE_FAMILY, MonitoringContextKeys, MonitorMetric
from hwbench.utils.helpers import cpu_list_to_range

MEAN = "mean"
ERROR = "error"


def init_matplotlib(args):
    try:
        matplotlib.use(args.engine)
    except ValueError:
        fatal(f"Cannot load matplotlib backend engine {args.engine}")
    matplotlib.rcParams["font.family"] = "monospace"


GRAPH_TYPES = ["perf", "perf_watt", "watts", "cpu_clock"]

# Extra headroom added above the data when no explicit ymax is provided, so the
# top curve is not merged with the frame. Graphs stay zero-based (comparable
# across CPUs/products); we only push the top of the axis a bit above the data.
YMAX_HEADROOM = 1.05
# Room before the 0 of an axis starting at 0, as a share of its end, so that a curve at 0, or
# starting at 0, is not merged with the frame
ZERO_MARGIN = 0.02

# The time axes keep at most this number of major ticks, on a round step multiple of the interval of the
# monitoring: the ones of 30 seconds of an hour of benchmark overlap each other
MAX_TIME_TICKS = 20
TIME_STEPS = (10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)
# Beyond this duration, in seconds, the time axes are in minutes
MINUTES_FROM = 600
TIME_LABEL = "Time [seconds]"
# The most of the smallest tick step the room takes, so that no tick is drawn before 0
ZERO_MARGIN_STEP = 0.4


# The markers of the curves, changing each time the 10 colors of the default cycle are all used,
# so that two curves of the same color still look different: shapes far apart, a dot, a cross, a
# triangle, a square, a plus and a diamond, all drawn at the same size, MARKER_SIZE, as a larger
# dot would not tell the curves apart
MARKERS = (".", "x", "^", "s", "+", "D")
MARKER_SIZE = 5


def curve_style(index: int) -> tuple[str, str]:
    """The color and the marker of the curve of an index on an axis, see MARKERS."""
    return f"C{index % 10}", MARKERS[(index // 10) % len(MARKERS)]


def zero_margin(axis, end: float) -> float:
    """The start of an axis from 0 to end, before 0 by ZERO_MARGIN of its end, but less than
    the smallest step of its ticks, major or minor: no tick is drawn before 0."""
    margin = end * ZERO_MARGIN
    steps = [np.diff(ticks).min() for ticks in (axis.get_majorticklocs(), axis.get_minorticklocs()) if len(ticks) > 1]
    if steps:
        margin = min(margin, ZERO_MARGIN_STEP * min(steps))
    return -margin


# The entries a legend beside the axes holds within their height: beyond, it is longer than the graph
MAX_LEGEND_ITEMS = 36


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
        title_note=None,
        legend_title="component [min; mean; stddev; max]\n",
    ) -> None:
        self.ax2: Axes | None = None
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
        self.set_title(title, show_source_file, title_note)
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self.set_filename(filename)
        self.needs_legend = True  # Does this graph need a legend to be rendered ?
        self.legend_title = legend_title

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
        points_to_plot=0,
        interval=0,
    ):
        """Set the ticks and axes limits."""
        self.needs_legend = legend
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

        # Keep a zero baseline so graphs stay comparable across CPUs/products,
        # but when no explicit ymax is given, push the top of the axis slightly
        # above the data so the highest curve is not merged with the frame.
        if ymax is None:
            data_top = self.ax.dataLim.ymax
            if data_top and 0 < data_top < float("inf"):
                ymax = data_top * YMAX_HEADROOM
        self.ax.set_ylim(None, ymin=0, ymax=ymax, emit=True, auto=True)
        self.ax.set_ylim(bottom=zero_margin(self.ax.yaxis, self.ax.get_ylim()[1]))
        # If we have a 2nd axis, let's prepare it
        if self.ax2:
            self.ax2.set_ylim(None, ymin=0, ymax=self.y2_max, emit=True, auto=True)
            top = self.ax2.get_ylim()[1]
            self.ax2.set_ylim(bottom=zero_margin(self.ax2.yaxis, top))
            self.ax2.yaxis.set_major_formatter(FuncFormatter(self.human_format))
            self.fig.tight_layout()  # otherwise the right y-label is slightly clipped
            # Evenly spread from 0 to the top, the margin below 0 having no tick
            ticks = len(self.ax.get_yticks()) - 2
            self.ax2.yaxis.set_major_locator(matplotlib.ticker.FixedLocator(np.linspace(0, top, ticks)))

        # If we have less than 15 points to render, let's use the real time interval
        if points_to_plot and points_to_plot < 30:
            x_major_locator = interval
            x_minor_locator = interval / 2

        # interval is only given for the time axes
        if interval and x_major_locator:
            x_major_locator, x_minor_locator = self.time_ticks(x_major_locator, x_minor_locator, interval)

        if x_major_locator:
            self.ax.set_xlim(None, xmin=0, emit=True)
            self.ax.xaxis.set_major_locator(
                MultipleLocator(x_major_locator),
            )

        if x_minor_locator:
            self.ax.xaxis.set_minor_locator(
                MultipleLocator(x_minor_locator),
            )
        else:
            self.ax.xaxis.set_minor_locator(AutoMinorLocator())
        if x_major_locator:
            self.ax.set_xlim(left=zero_margin(self.ax.xaxis, self.ax.get_xlim()[1]))

        self.ax.yaxis.set_major_formatter(FuncFormatter(self.human_format))
        self.prepare_grid()

    def time_ticks(self, x_major, x_minor, interval) -> tuple[float, float]:
        """The steps of the ticks of a time axis: the ones given while they are at most MAX_TIME_TICKS,
        otherwise the first round step giving at most MAX_TIME_TICKS, multiple of the interval; beyond
        MINUTES_FROM, the axis is in minutes."""
        duration = self.ax.dataLim.xmax
        if not 0 < duration < float("inf"):
            return x_major, x_minor
        if duration > MINUTES_FROM:
            self.ax.xaxis.set_major_formatter(FuncFormatter(lambda seconds, _: f"{seconds / 60:g}"))
            if self.ax.get_xlabel() == TIME_LABEL:
                self.ax.set_xlabel("Time [minutes]")
        if duration / x_major <= MAX_TIME_TICKS:
            return x_major, x_minor
        step = next(
            (step for step in TIME_STEPS if duration / step <= MAX_TIME_TICKS and step % interval == 0),
            TIME_STEPS[-1],
        )
        # Five minor ticks per major one when they fall on the samples, two otherwise
        minor = step / 5 if (step / 5) % interval == 0 else step / 2
        return step, minor

    def human_format(self, num, pos=None):
        """Return format in human readable units."""
        # This function is compatible with FuncFormatter and fmt
        unit = ""
        if num >= 1e9:
            num *= 1e-9
            unit = "G"
        elif num >= 1e6:
            num *= 1e-6
            unit = "M"
        elif num >= 1e3:
            num *= 1e-3
            unit = "K"
        return f"{num:.2f}{unit}"

    def prepare_grid(self):
        self.ax.grid(which="major", linewidth=1)
        self.ax.grid(which="minor", linewidth=0.2, linestyle="dashed")

    def set_title(self, title, show_source_file=None, title_note=None):
        """Set the graph title"""
        # Tracked so render() can hand it to savefig's bbox_extra_artists: the box
        # sits below the axes and can otherwise be cropped out by bbox_inches="tight".
        self.source_text = None
        # When a note is present, push the main title up to leave room for the
        # note, which is rendered just above the axes in bold dark red.
        self.ax.set_title(title, pad=28 if title_note else None)
        if title_note:
            self.ax.text(
                0.5,
                1.0,
                title_note,
                transform=self.ax.transAxes,
                horizontalalignment="center",
                verticalalignment="bottom",
                color="darkred",
                fontweight="bold",
                fontsize=14,
            )
        if show_source_file:
            # place a text box in upper left in axes coords
            props = dict(boxstyle="round", facecolor="white", alpha=0.5)
            self.source_text = self.ax.text(
                0,
                -0.1,
                f"data plotted from {show_source_file.get_filename()}",
                transform=self.ax.transAxes,
                fontsize=14,
                verticalalignment="top",
                bbox=props,
                # Use a proportional font here: with the cairo backend the width
                # of monospace text is mismeasured, so its rounded box comes out
                # too narrow and the (often long) filename spills past the frame.
                fontfamily="sans-serif",
            )

    def get_ax(self):
        """Return the ax object."""
        return self.ax

    def get_ax2(self):
        """Return the ax2 object (for the 2nd y axis)."""
        return self.ax2

    def trace_events(self):
        """Trace events of the graphics"""
        # if we don't have events or if this graph will not have a legend (like BarGraphs),
        # do not add events
        if not self.args.events or not self.needs_legend:
            return

        colors = [
            "tab:blue",
            "tab:orange",
            "tab:green",
            "tab:red",
            "tab:purple",
            "tab:brown",
            "tab:pink",
            "tab:cyan",
            "tab:olive",
        ]
        # Let's add all events and color them,
        for event, event_color in zip(self.args.events, cycle(colors)):
            ymin, ymax = self.get_ax().get_ylim()
            self.ax.axvspan(
                event.get_start_time(),
                event.get_start_time() + event.get_duration(),
                ymin,
                ymax,
                label=f"Event {event.get_name()}",
                alpha=0.2,
                color=event_color,
            )

    def render(self, extra_legend=None):
        """Render the graph to a file.

        extra_legend: one or more additional, manually placed legends that
        must be taken into account when computing the tight bounding box.
        """
        # Retrieve the rendering file format
        file_format = self.args.format
        if extra_legend is None:
            legends = []
        elif isinstance(extra_legend, (list, tuple)):
            legends = list(extra_legend)
        else:
            legends = [extra_legend]

        # Keep the "data plotted from" box in the tight bounding box: it sits below
        # the axes and can otherwise be cropped out by bbox_inches="tight".
        if self.source_text is not None:
            legends.append(self.source_text)

        # Trace the events passed on the command line
        self.trace_events()

        # Having vertical xticks makes it scalable for large number of cores
        self.ax.tick_params(axis="x", labelrotation=90)

        # Plot the legend if necessary
        # (Some graphs, like BarGraphs, do not need legend)
        if self.needs_legend:
            # Upper left
            handles, labels = self.ax.get_legend_handles_labels()
            if handles:
                legends.append(self.ax.legend(bbox_to_anchor=(-0.1, 1), title=self.legend_title))
            if self.ax2:
                # Anchor the legend by its left edge, just right of the 2nd y-axis
                # (past its tick labels and title), so it grows outward instead of
                # back over the axis regardless of how wide/long its labels get.
                handles2, labels2 = self.ax2.get_legend_handles_labels()
                if handles2:
                    legends.append(self.ax2.legend(loc="upper left", bbox_to_anchor=(1.05, 1), title=self.legend_title))

        self.fig.savefig(
            f"{self.output_dir}/{self.filename}.{file_format}",
            format=file_format,
            dpi=self.args.dpi,
            bbox_inches="tight",
            pad_inches=1,
            bbox_extra_artists=legends,
        )
        self.fig.clear()
        plt.close(self.fig)


def fp(value: float, max_value_length=0) -> str:
    # Return the string representation of a normalized float
    result = f"{value:.1f}"
    # If we force the string length:
    if max_value_length:
        return f"{result:>{max_value_length}}"
    return result


def draw_lines(ax, x_serie, y_series) -> None:
    """Draw curves without label as a single LineCollection: visually identical to one plot() per
    curve, but much cheaper for hundreds of them."""
    segments = [np.column_stack([x_serie, y_serie]) for y_serie in y_series]
    # Reproduce the per-line color cycling matplotlib's plot() would apply.
    cycle_colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    colors = [cycle_colors[i % len(cycle_colors)] for i in range(len(segments))]
    ax.add_collection(
        LineCollection(
            segments,
            colors=colors,
            linewidths=plt.rcParams["lines.linewidth"],
            capstyle=plt.rcParams["lines.solid_capstyle"],
        )
    )
    # add_collection updates the data limits but, unlike plot(), does not
    # refresh the view; do it so the axes autoscale to the data as usual.
    ax.autoscale_view()


def get_max_value_string_length(serie) -> int:
    # Get the max value of a serie
    return max(len(fp(x)) for x in serie)


def statistics_in_label(label: str, serie: np.ndarray, max_title_length=0, max_value_length=0) -> str:
    """Return 'label + [min, mean, stddev, max]'"""

    if not max_title_length:
        max_title_length = len(label)

    # The gaps of a device that did not answer, NaN, are not part of the statistics
    serie = np.asarray(serie, dtype=float)
    serie = serie[np.isfinite(serie)] if np.isfinite(serie).any() else serie
    return f"{label:{max_title_length}} [{fp(np.min(serie), max_value_length)}; {fp(np.mean(serie), max_value_length)}; {fp(np.std(serie), max_value_length)}; {fp(np.max(serie), max_value_length)}]"


def numa_core_blocks(cpus, width: int = 3) -> str:
    """Render a cpu list as aligned, individually bracketed range blocks.

    Reuses cpu_list_to_range() and only reformats its output: each range block
    gets its own "[]", the numbers are padded to `width` digits with the dash
    centered, so blocks line up in a monospace legend.
    e.g. [0..7, 64..71] -> "[0  -  7] [64 - 71]".
    """
    blocks = []
    for block in cpu_list_to_range(list(cpus)).split(", "):
        low, _, high = block.partition("-")
        if high:
            # Right-justify both bounds so numbers align and the dash stays centered.
            blocks.append(f"[{low:>{width}}-{high:>{width}}]")
        else:
            # A single core (no range): keep the same block width, right-aligned.
            blocks.append(f"[{block:>{2 * width + 1}}]")
    return ", ".join(blocks)


def numa_aggregated_components(
    bench: Bench, component_type: MonitoringContextKeys, numa_nodes, pinned_cores=None
) -> list[MonitorMetric]:
    """Aggregate per-core metrics into one synthetic metric per NUMA domain.

    For each NUMA domain, average (per sample) the metric of the cores that
    belong to it. When pinned_cores (a set of "Core_N" names) is given, only the
    pinned cores of each domain are averaged and domains with no pinned core are
    dropped. Domains with no monitored core are skipped. The result is a list of
    MonitorMetric objects (one per domain) ready to feed generic_graph.
    """
    samples_count = bench.get_samples_count()
    components = []
    for node in sorted(numa_nodes):
        core_names = {f"Core_{cpu}" for cpu in numa_nodes[node]}
        if pinned_cores is not None:
            core_names &= pinned_cores
        if not core_names:
            continue
        cores = bench.get_all_metrics(component_type, names=core_names)
        if not cores:
            continue
        means = []
        for sample in range(samples_count):
            values = [c.get_mean()[sample] for c in cores if sample < len(c.get_mean())]
            means.append(float(np.mean(values)) if values else 0.0)
        metric = MonitorMetric(f"NUMA {node}", cores[0].get_unit())
        metric.mean = means
        metric.full_name = f"NUMA {node}"
        components.append(metric)
    return components


def numa_cores_legend(ax, node_cores):
    """Add a left-side box listing each NUMA domain's cores in condensed form.

    node_cores is an ordered list of (domain, cpus) pairs (top to bottom). The
    box is anchored well to the left of the Y axis so it does not collide with
    it, even with 3-digit core numbers.
    """
    node_width = max((len(str(node)) for node, _ in node_cores), default=1)
    labels = [f"NUMA {node:>{node_width}}: {numa_core_blocks(cpus)}" for node, cpus in node_cores]
    handles = [Line2D([], [], linestyle="none") for _ in labels]
    return ax.legend(
        handles,
        labels,
        loc="upper right",
        bbox_to_anchor=(-0.10, 1),
        title="NUMA domain [cores]",
        handlelength=0,
        handletextpad=0,
    )


def _render_numa_heatmap(graph, nodes, matrix, extra_legend=None) -> None:
    """Draw a NUMA domain x domain distance matrix onto graph.

    Cells are colored/annotated by the inter-domain distance.
    """
    ax = graph.get_ax()
    image = ax.imshow(matrix, cmap="viridis")
    graph.fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="NUMA distance")
    labels = [f"NUMA {node}" for node in nodes]
    ax.set_xticks(range(len(nodes)))
    ax.set_yticks(range(len(nodes)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    # Text color threshold so annotations stay readable over the colormap.
    threshold = (matrix.max() + matrix.min()) / 2
    for i in range(len(nodes)):
        for j in range(len(nodes)):
            text, weight = f"{matrix[i, j]:.0f}", "normal"
            ax.text(
                j,
                i,
                text,
                ha="center",
                va="center",
                fontsize=8,
                fontweight=weight,
                color="white" if matrix[i, j] < threshold else "black",
            )
    graph.needs_legend = False
    graph.render(extra_legend=extra_legend)


def numa_distance_heatmap(args, output_dir, trace) -> int:
    """Render the host's NUMA distance matrix as a heatmap.

    This is a per-host topology figure (one per trace), independent of any
    benchmark or performance metric: cell color/value is the distance between
    two NUMA domains, so which domains are close/far is visible at a glance.
    Needs the distance matrix with at least two domains; otherwise nothing is
    rendered.
    """
    distances = trace.get_numa_distances()
    if not distances or len(distances) < 2:
        return 0
    nodes = sorted(distances)
    try:
        matrix = np.array([[distances[src][dst] for dst in nodes] for src in nodes], dtype=float)
    except (KeyError, IndexError):
        return 0

    cpu = trace.get_cpu()
    dmi = trace.get_dmi()
    title = f"NUMA distances of {trace.get_name()}{context_header(args)}\n{args.title}\n\n"
    title += "".join(f"CDU: {cdu}\n" for cdu in trace.get_cdu_lines())
    title += f"System: {dmi['serial']} {dmi['product']}"
    location = trace.get_location_line()
    if location:
        title += f"\nLocation: {location}"
    title += f"\nProcessor: {cpu.get('sockets', 1)}x {cpu['model']} - {cpu['numa_domains']} NUMA domains"
    graph = Graph(
        args,
        title,
        "NUMA domain",
        "NUMA domain",
        output_dir.joinpath(trace.get_name()),
        "NUMA distances",
        square=True,
        show_source_file=trace,
    )
    numa_nodes = trace.get_numa_nodes()
    legend = numa_cores_legend(graph.get_ax(), [(node, numa_nodes.get(node, [])) for node in nodes])
    _render_numa_heatmap(graph, nodes, matrix, extra_legend=legend)
    return 1


def _int_ranges(values, width: int = 0) -> str:
    """Condense a list of ints into ranges, keeping singletons (e.g. '0, 2-4').

    Unlike cpu_list_to_range(), a lone value is emitted as-is rather than dropped.
    Numbers are right-justified to `width` digits (0 = no padding) so ranges stay
    aligned.
    """
    ordered = sorted(values)
    if not ordered:
        return ""
    parts = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
        else:
            parts.append(f"{start:>{width}}" if start == prev else f"{start:>{width}}-{prev:>{width}}")
            start = prev = value
    parts.append(f"{start:>{width}}" if start == prev else f"{start:>{width}}-{prev:>{width}}")
    return ", ".join(parts)


def write_benchmarks_summary(args, output_dir, trace) -> int:
    """Write a text table describing every benchmark run of the trace.

    One row per benchmark (e.g. avx_0, avx_1, ...): the job it belongs to, the
    engine/module and variant (engine_module_parameter) it exercises, the worker
    count, the components it loaded and per-run duration. A column describing a
    kind of component (the pinned cores, the GPUs, the disk) is only present when
    the engine of a benchmark of the trace loads that kind. It is a per-host, plain-text
    companion to the environmental graphs -- a quick key to what each benchmark
    actually tested, in benchmark (job_number) order. Written to
    benchmarks_summary.txt; returns 1 when written.
    """
    benches = trace.bench_list()
    if not benches:
        return 0

    # One row per benchmark, ordered by job_number (avx_0, avx_1, ... then cpu_*).
    ordered = sorted(benches, key=lambda name: trace.bench(name).get("job_number"))

    # core -> NUMA node lookup, to report which domains a benchmark's pinned cores span.
    numa_nodes = trace.get_numa_nodes()
    core_to_node = {core: node for node, cores in numa_nodes.items() for core in cores}

    def cpu_columns(bench) -> dict[str, str]:
        if not bench.cpu_pin():
            return {"Pinned cores": "no", "NUMA nodes": "no"}
        # NUMA domains the pinned cores belong to (condensed and bracketed, node
        # numbers padded to 2 digits so ranges align, e.g. "[ 0- 3]").
        nodes = sorted({core_to_node[core] for core in bench.cpu_pin() if core in core_to_node})
        return {
            # Condensed list of pinned cores with digits padded to 3 columns so
            # the ranges stay aligned even with 3-digit core numbers.
            "Pinned cores": numa_core_blocks(bench.cpu_pin()),
            "NUMA nodes": f"[{_int_ranges(nodes, width=2)}]" if nodes else "-",
        }

    def gpu_columns(bench) -> dict[str, str]:
        return {"GPUs": f"[{cpu_list_to_range(bench.gpu_list())}]" if bench.gpu_list() else "no"}

    def disk_columns(bench) -> dict[str, str]:
        return {"Disk": (bench.get("custom_parameters") or {}).get("disk") or "no"}

    # The columns of each kind of component, in the order they are shown
    resource_columns = {
        Resource.CPU: (["Pinned cores", "NUMA nodes"], cpu_columns),
        Resource.GPU: (["GPUs"], gpu_columns),
        Resource.DISK: (["Disk"], disk_columns),
    }
    used = {resource for name in ordered for resource in trace.bench(name).resources()}
    resources = [resource for resource in resource_columns if resource in used]

    headers = [
        "Benchmark",
        "Job",
        "Engine / module",
        "Variant",
        "Workers",
        *[column for resource in resources for column in resource_columns[resource][0]],
        "Duration (s)",
    ]
    right_aligned = {"Workers", "NUMA nodes", "Duration (s)"}
    rows = []  # type: list
    for bench_name in ordered:
        bench = trace.bench(bench_name)
        row = {
            "Benchmark": bench_name,
            "Job": bench.job_name(),
            "Engine / module": f"{bench.engine()} / {bench.engine_module()}",
            "Variant": bench.engine_module_parameter(),
            "Workers": str(bench.workers()),
            "Duration (s)": str(int(round(bench.duration()))),
        }
        for resource in resources:
            columns, values = resource_columns[resource]
            # A benchmark not loading this kind of component has nothing to show in its columns
            row |= values(bench) if resource in bench.resources() else dict.fromkeys(columns, "-")
        rows.append(row)

    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(row[header]))

    def _cell(header, value) -> str:
        return str(value).rjust(widths[header]) if header in right_aligned else str(value).ljust(widths[header])

    def _line(cells) -> str:
        return "  ".join(_cell(header, cells[header]) for header in headers)

    # Header: the same host description as the graphs, with System / Bios / Kernel
    # split onto their own (label-aligned) lines, plus a NUMA-nodes summary.
    dmi = trace.get_dmi()
    cpu = trace.get_cpu()
    kernel = trace.get_kernel()
    info = [
        *(("CDU", cdu) for cdu in trace.get_cdu_lines()),
        ("System", f"{dmi['serial']} {dmi['product']}"),
        *([("Location", location)] if (location := trace.get_location_line()) else []),
        ("Bios", f"v{dmi['bios']['version']}"),
        ("Kernel", kernel["release"]),
        (
            "Processor",
            f"{cpu.get('sockets', 1)}x {cpu['model']} - "
            f"{cpu['physical_cores']} physical cores and {cpu['numa_domains']} NUMA domains",
        ),
        *gpu_description(trace.get_gpus()),
    ]
    label_width = max(len(label) for label, _ in info)
    lines = [f"Benchmarks summary - {trace.get_name()}{context_header(args)}", args.title or "", ""]
    lines += [f"{label:<{label_width}} : {value}" for label, value in info]

    if numa_nodes:
        node_width = max(len(str(node)) for node in numa_nodes)
        lines.append("")
        lines.append(f"NUMA nodes ({len(numa_nodes)}):")
        lines += [f"  NUMA {node:>{node_width}} : {numa_core_blocks(numa_nodes[node])}" for node in sorted(numa_nodes)]

    gpus = trace.get_gpus()
    if gpus:
        # Where each GPU sits, so a misbehaving one can be found in the chassis
        indexes = sorted(gpus, key=int)
        gpu_width = max(len(index) for index in indexes)
        locator_width = max(len(gpus[index].get("locator") or "unknown") for index in indexes)
        lines.append("")
        lines.append(f"GPUs ({len(gpus)}):")
        lines += [
            f"  GPU {index:>{gpu_width}} : {gpus[index].get('locator') or 'unknown':<{locator_width}}  {gpus[index].get('uuid')}"
            for index in indexes
        ]

    lines += ["", _line({header: header for header in headers}), "  ".join("-" * widths[header] for header in headers)]
    lines += [_line(row) for row in rows]
    text = "\n".join(line.rstrip() for line in lines) + "\n"

    trace_dir = output_dir.joinpath(trace.get_name())
    trace_dir.mkdir(parents=True, exist_ok=True)
    summary_file = trace_dir.joinpath("benchmarks_summary.txt")
    summary_file.write_text(text)
    if getattr(args, "verbose", False):
        print(f"benchmarks: {trace.get_name()} - wrote {len(rows)} entries to {summary_file}")
    return 1


def numa_distribution_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: MonitoringContextKeys,
    item_title: str,
    numa_nodes,
    dir_suffix=None,
    pinned_cores=None,
    title_note=None,
) -> int:
    """Render the per-NUMA-domain distribution of a metric at steady state (one violin + box per domain).

    Each domain gets its own violin built from its cores' steady-state (mean
    over the run) values, so core-to-core uniformity can be compared across
    domains at a glance -- same idea as component_distribution_graph, split by NUMA
    domain instead of blended into a single body. When pinned_cores is given,
    only the pinned cores of each domain feed its violin and domains with no
    pinned core are skipped. The Y axis autoscales to the data.
    """
    domains = []
    for node in sorted(numa_nodes):
        core_names = {f"Core_{cpu}" for cpu in numa_nodes[node]}
        if pinned_cores is not None:
            core_names &= pinned_cores
        if not core_names:
            continue
        cores = bench.get_all_metrics(component_type, names=core_names)
        if not cores:
            continue
        values = [float(np.mean(core.get_mean())) for core in cores]
        domains.append((node, values))
    if not domains:
        return 0
    unit = bench.get_metric_unit(component_type)

    trace = bench.get_trace()
    title = f'{item_title} per-NUMA-domain distribution during "{bench.get_bench_name()}" benchmark job{context_header(args)}\n{args.title}\n\n Stressor: '
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph_dir = output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{component_type!s}")
    if dir_suffix:
        graph_dir = graph_dir.joinpath(dir_suffix)
    graph = Graph(
        args,
        title,
        "",
        unit,
        graph_dir,
        f"{item_title} - distribution",
        show_source_file=trace,
        title_note=title_note,
    )
    ax = graph.get_ax()
    positions = list(range(1, len(domains) + 1))
    domain_values = [values for _, values in domains]
    parts = ax.violinplot(domain_values, positions=positions, widths=0.7, showextrema=False)
    for body in parts["bodies"]:
        body.set_facecolor("tab:blue")
        body.set_alpha(0.25)
    ax.boxplot(
        domain_values,
        positions=positions,
        widths=0.15,
        showmeans=True,
        meanline=True,
        medianprops=dict(color="tab:red"),
        meanprops=dict(color="tab:green", linestyle="--"),
        flierprops=dict(marker=".", markersize=3, alpha=0.4),
    )
    ax.set_xticks(positions)
    ax.set_xticklabels([f"NUMA {node}" for node, _ in domains])
    # Same two-tier Y grid as the linearity-deviation graph (solid major lines
    # plus a fainter dashed midline between the major Y ticks), but no X grid:
    # vertical lines would cut through the violins and hide their shape.
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.grid(which="major", axis="y", linewidth=0.7, linestyle="solid", color="0.6")
    ax.grid(which="minor", axis="y", linewidth=0.6, linestyle="dashed", color="0.75")

    # Left-side box listing each domain's cores in condensed form, like the
    # heatmap's legend -- useful to see exactly which cores fed each violin,
    # especially on the pinned view where a domain may keep only a few.
    pinned_cpus = None
    if pinned_cores is not None:
        pinned_cpus = {int(name.split("_")[1]) for name in pinned_cores}
    node_cores = []
    for node, _ in domains:
        cpus = numa_nodes[node]
        if pinned_cpus is not None:
            cpus = [cpu for cpu in cpus if cpu in pinned_cpus]
        node_cores.append((node, cpus))
    cores_legend = numa_cores_legend(ax, node_cores)
    stats_legend = ax.legend(
        handles=[
            Line2D([], [], color="tab:red", label="median"),
            Line2D([], [], color="tab:green", linestyle="--", label="mean"),
        ],
        loc="upper right",
        fontsize=8,
    )
    ax.add_artist(cores_legend)
    graph.needs_legend = False
    graph.render(extra_legend=[cores_legend, stats_legend])
    return 1


def numa_performance_heatmap(
    args,
    output_dir,
    bench: Bench,
    component_type: MonitoringContextKeys,
    item_title: str,
    numa_nodes,
    dir_suffix=None,
    pinned_cores=None,
    title_note=None,
) -> int:
    """Render a NUMA-domain x time heatmap of a per-core metric.

    Y axis is the NUMA domains, X axis is time (as in the line graphs of the
    same directory) and the color is the domain's average metric value at each
    monitoring step. It is the same data as the per-domain line graph, shown as
    a heatmap; it lives next to it (all_numa/pinned_numa).
    """
    components = numa_aggregated_components(bench, component_type, numa_nodes, pinned_cores)
    if not components:
        return 0
    unit = bench.get_metric_unit(component_type)
    interval = bench.get_time_interval()
    matrix = np.array([component.get_mean() for component in components], dtype=float)
    domains = len(components)
    samples = matrix.shape[1]

    trace = bench.get_trace()
    title = f'{item_title} during "{bench.get_bench_name()}" benchmark job{context_header(args)}\n{args.title}\n\n Stressor: '
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph_dir = output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{component_type!s}")
    if dir_suffix:
        graph_dir = graph_dir.joinpath(dir_suffix)
    graph = Graph(
        args,
        title,
        "Time [seconds]",
        "NUMA domain",
        graph_dir,
        f"{item_title} - heatmap",
        show_source_file=trace,
        title_note=title_note,
    )
    ax = graph.get_ax()
    image = ax.imshow(
        matrix,
        aspect="auto",
        cmap="viridis",
        interpolation="nearest",
        extent=(0, samples * interval, domains - 0.5, -0.5),
    )
    graph.fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label=unit)
    ax.set_yticks(range(domains))
    ax.set_yticklabels([component.get_full_name() for component in components])

    # Separate box on the left listing each domain's cores in condensed form,
    # like the component legend of the line graphs.
    pinned_cpus = None
    if pinned_cores is not None:
        pinned_cpus = {int(name.split("_")[1]) for name in pinned_cores}
    node_cores = []
    for component in components:
        node = int(component.get_full_name().split()[1])
        cpus = numa_nodes[node]
        if pinned_cpus is not None:
            cpus = [cpu for cpu in cpus if cpu in pinned_cpus]
        node_cores.append((node, cpus))
    legend = numa_cores_legend(ax, node_cores)
    graph.needs_legend = False
    graph.render(extra_legend=legend)
    return 1


def component_distribution_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: MonitoringContextKeys,
    item_title: str,
    dir_suffix=None,
    names=None,
    title_note=None,
    filter="Core",
    components=None,
    item_name="core",
) -> int:
    """Render the per-component distribution of a metric at steady state (violin + box).

    Each component's steady-state value (mean over the run) becomes one point;
    the violin shows their density and the box shows median/mean/quartiles/
    outliers, so the component-to-component uniformity is visible at a glance.
    names restricts the components (pinned view). The Y axis autoscales to the
    data (a distribution is unreadable squished against a zero baseline).

    It defaults to the cpu cores; pass filter/components and item_name to render
    another kind of component, i.e the GPUs.
    """
    if components is None:
        components = bench.get_all_metrics(component_type, filter, names)
    else:
        # get_all_metrics() already drops the components that never reported a
        # sample -- all-smi registers those for the metrics a GPU does not
        # support -- but a caller-supplied list has not been through it, and
        # averaging an empty serie would inject a NaN into the distribution.
        components = [component for component in components if component.get_mean()]
    if not components:
        return 0
    unit = components[0].get_unit() or bench.get_metric_unit(component_type)
    values = [float(np.mean(component.get_mean())) for component in components]

    trace = bench.get_trace()
    title = f'{item_title} per-{item_name} distribution during "{bench.get_bench_name()}" benchmark job{context_header(args)}\n{args.title}\n\n Stressor: '
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph_dir = output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{component_type!s}")
    if dir_suffix:
        graph_dir = graph_dir.joinpath(dir_suffix)
    graph = Graph(
        args,
        title,
        "",
        unit,
        graph_dir,
        f"{item_title} - distribution",
        square=True,
        show_source_file=trace,
        title_note=title_note,
    )
    ax = graph.get_ax()
    parts = ax.violinplot([values], positions=[1], widths=0.7, showextrema=False)
    for body in parts["bodies"]:
        body.set_facecolor("tab:blue")
        body.set_alpha(0.25)
    ax.boxplot(
        [values],
        positions=[1],
        widths=0.15,
        showmeans=True,
        meanline=True,
        medianprops=dict(color="tab:red"),
        meanprops=dict(color="tab:green", linestyle="--"),
        flierprops=dict(marker=".", markersize=3, alpha=0.4),
    )
    ax.set_xticks([1])
    ax.set_xticklabels([f"{len(values)} {item_name}s"])
    # Same two-tier Y grid as the linearity-deviation graph (solid major lines
    # plus a fainter dashed midline between the major Y ticks), but no X grid:
    # vertical lines would cut through the violins and hide their shape.
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.grid(which="major", axis="y", linewidth=0.7, linestyle="solid", color="0.6")
    ax.grid(which="minor", axis="y", linewidth=0.6, linestyle="dashed", color="0.75")
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
    return 1


def generic_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: MonitoringContextKeys,
    item_title: str,
    second_axis: MonitoringContextKeys | None = None,
    filter=None,
    names=None,
    dir_suffix=None,
    title_note=None,
    components=None,
) -> int:
    outfile = f"{item_title}"
    trace = bench.get_trace()

    if components is None:
        components = bench.get_all_metrics(component_type, filter, names)
    if not len(components):
        title = f"{item_title}: no {component_type!s} metric found"
        if filter:
            title += f" with filter = '{filter}'"
        return 0

    samples_count = bench.get_samples_count()
    # The unit of the components being rendered, not the one of the first metric
    # of the context: a context can hold several units (i.e. the GPU context
    # holds a percentage and a memory size).
    unit = components[0].get_unit() or bench.get_metric_unit(component_type)
    if not unit:
        raise Exception(f"Could not find unit for metric {item_title}")

    title = f'{item_title} during "{bench.get_bench_name()}" benchmark job{context_header(args)}\n{args.title}\n\n Stressor: '
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph_dir = output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{component_type!s}")
    if dir_suffix:
        graph_dir = graph_dir.joinpath(dir_suffix)
    graph = Graph(
        args,
        title,
        "Time [seconds]",
        unit,
        graph_dir,
        outfile,
        show_source_file=trace,
        title_note=title_note,
    )

    if second_axis:
        outfile += f"_vs_{second_axis}"
        graph.set_filename(outfile)
        if second_axis == MonitoringContextKeys.Thermal:
            graph.set_y2_axis("Thermal (°C)", 110)
        elif second_axis == MonitoringContextKeys.PowerConsumption:
            graph.set_y2_axis("Power (Watts)")

    if args.verbose:
        print(
            f"{trace.get_name()}/{bench.get_bench_name()}: {len(components)} {component_type!s} to graph with {samples_count} samples"
        )

    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data2_serie = {}  # type: dict[str, list]
    for sample in range(0, samples_count):
        time = sample * bench.get_time_interval()
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            if component.get_full_name() not in data_serie:
                data_serie[component.get_full_name()] = []
            # If we are missing some datapoints ....
            if len(component.get_mean()) <= sample:
                # If the user didn't explicitly agreed to be replaced by 0, let's be fatal
                if not args.ignore_missing_datapoint:
                    fatal(
                        f"{trace.get_name()}/{bench.get_bench_name()}: {component.get_full_name()} is missing the {sample + 1}th data point.\
 Use --ignore-missing-datapoint to ignore this case. Generated graphs will be partially incorrect."
                    )
                else:
                    # User is fine with a missing data to be replaced.
                    # Let's do that so we can render things properly.

                    # Let's pick the last known value
                    if args.ignore_missing_datapoint == "last":
                        data_serie[component.get_full_name()].append(component.get_mean()[-1])
                    else:
                        # Replace it by a zero
                        data_serie[component.get_full_name()].append(0)
            else:
                data_serie[component.get_full_name()].append(component.get_mean()[sample])

        if second_axis:
            for entry in bench.get_monitoring_metric(second_axis).values():
                for sensor, measure in entry.items():
                    # We don't plot sensor on y2 if already plot on y1. Only a
                    # sensor of the very same context can be: the same component
                    # name lives in several contexts (Freq.GPU_0, Thermal.GPU_0,
                    # PowerConsumption.GPU_0) and those are distinct metrics.
                    # The cores are named rather than derived from 'filter':
                    # they are the only family numerous enough to swamp y2, and
                    # excluding the family of y1 would drop the very sensor a
                    # '<GPU metric>_vs_Thermal' graph is drawn for.
                    if (second_axis == component_type and sensor in data_serie) or sensor.startswith(CORE_FAMILY):
                        continue
                    if sensor not in data2_serie:
                        data2_serie[sensor] = []
                    if len(measure.get_mean()) <= sample:
                        # If the user didn't explicitly agreed to be replaced by 0, let's be fatal
                        if not args.ignore_missing_datapoint:
                            fatal(
                                f"{trace.get_name()}/{bench.get_bench_name()}: second axis of {sensor}: {measure.get_full_name()} is missing the {sample + 1}th data point.\
         Use --ignore-missing-datapoint to ignore this case. Generated graphs will be partially incorrect."
                            )
                        else:
                            # User is fine with a missing data to be replaced.
                            # Let's do that so we can render things properly.
                            if args.ignore_missing_datapoint == "last":
                                # Let's pick the last known value
                                data2_serie[sensor].append(measure.get_mean()[-1])
                            else:
                                # Replace it by a zero
                                data2_serie[sensor].append(0)
                    else:  # the actual data
                        data2_serie[sensor].append(measure.get_mean()[sample])
            # If we are plotting the power consumption, having the PSUs would be useful to compare with.
            if second_axis == MonitoringContextKeys.PowerConsumption:
                psus = bench.get_psu_power()
                if psus:
                    if MonitoringContextKeys.PowerSupplies not in data2_serie:
                        data2_serie[MonitoringContextKeys.PowerSupplies] = []
                    data2_serie[MonitoringContextKeys.PowerSupplies].append(psus[sample])

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]

    # data2_serie is empty when every sensor of the second axis was filtered out
    # (all of them already on y1, or all of them cores): nothing to plot there.
    if second_axis and data2_serie:
        max_title_length = max(len(data2_item) for data2_item in data2_serie)
        max_value_length = max(
            get_max_value_string_length(np.array(data2_serie[data2_item])) for data2_item in data2_serie
        )
        for index, data2_item in enumerate(data2_serie):
            y2_serie = np.array(data2_serie[data2_item])[order]
            y2_label = statistics_in_label(str(data2_item), y2_serie, max_title_length, max_value_length)
            # Beyond the 10 colors of the cycle, the curves change of marker, see curve_style()
            color, marker = curve_style(index)
            graph.get_ax2().plot(
                x_serie, y2_serie, "", label=y2_label, color=color, marker=marker, markersize=MARKER_SIZE
            )

    # If we have more than MAX_LEGEND_ITEMS items to draw, labels will not fit and makes the
    # drawing hard to read. In that case there is no legend, so we can draw all
    # the lines as a single LineCollection: this is visually identical but much
    # cheaper than creating one Line2D per component (e.g. 320 CPU cores).
    if len(components) <= MAX_LEGEND_ITEMS:
        max_title_length = max(len(component.get_full_name()) for component in components)
        max_value_length = max(
            get_max_value_string_length(np.array(data_serie[component.get_full_name()])) for component in components
        )
        for index, component in enumerate(components):
            y_serie = np.array(data_serie[component.get_full_name()])[order]
            y_label = statistics_in_label(component.get_full_name(), y_serie, max_title_length, max_value_length)
            # The lines of the first axis have no marker, until the colors of the cycle are all used
            color, marker = curve_style(index)
            graph.get_ax().plot(
                x_serie,
                y_serie,
                "",
                label=y_label,
                color=color,
                marker=marker if index >= 10 else None,
                markersize=MARKER_SIZE,
            )
    else:
        draw_lines(
            graph.get_ax(),
            x_serie,
            [np.array(data_serie[component.get_full_name()])[order] for component in components],
        )

    graph.prepare_axes(
        30,
        15,
        (bench.get_monitoring_metric_axis(unit)),
        points_to_plot=len(data_serie[next(iter(data_serie))]),
        interval=bench.get_time_interval(),
    )

    graph.render()
    return 1


def yerr_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: MonitoringContextKeys,
    component: MonitorMetric,
    prefix="",
):
    trace = bench.get_trace()
    samples_count = bench.get_samples_count()
    unit = bench.get_metric_unit(component_type)
    if not unit:
        raise InvalidValue("Could not find unit")

    time_serie = []
    data_serie: dict[str, list] = {}
    data_serie[MEAN] = []
    data_serie[ERROR] = []
    for sample in range(0, samples_count):
        time = sample * bench.get_time_interval()
        time_serie.append(time)
        mean_value = component.get_mean()[sample]
        data_serie[ERROR].append(
            (
                mean_value - component.get_min()[sample],
                component.get_max()[sample] - mean_value,
            )
        )
        data_serie[MEAN].append(mean_value)

    title = f'{prefix}{component.get_name()} during "{bench.get_bench_name()}" benchmark job{context_header(args)}\n\n Stressor: '
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    y_serie = np.array(data_serie[MEAN])[order]
    yerror_serie = np.array(data_serie[ERROR]).T

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        unit,
        output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{component_type!s}"),
        component.get_name(),
        show_source_file=trace,
    )

    graph.get_ax().errorbar(
        x_serie,
        y_serie,
        yerr=yerror_serie,
        fmt="-b",
        ecolor="r",
        capsize=4,
        label=statistics_in_label(
            component.get_name(), y_serie, len(component.get_full_name()), get_max_value_string_length(y_serie)
        ),
    )
    graph.prepare_axes(
        30,
        15,
        bench.get_monitoring_metric_axis(unit),
        points_to_plot=len(data_serie[next(iter(data_serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render()
    return 1


class InvalidValue(Exception):
    pass
