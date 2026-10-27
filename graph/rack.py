from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize, to_rgba
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox, ScaledTranslation

from graph.cdu import CIRCUIT_TEMPERATURES
from graph.common import cdu_header, context_header, location_header
from graph.graph import MARKER_SIZE, Graph, curve_style, get_max_value_string_length, statistics_in_label
from graph.group import place_suffix
from graph.trace import Bench, Trace
from hwbench.bench.monitoring_structs import (
    CDU_FAMILY,
    GPU_FAMILY,
    MonitoringContextKeys,
)

# The prefixes of the positions in a rack, removed before reading their number: U12 in a 19" rack,
# OU12 in an OCP one; the longest first
POSITION_PREFIXES = ("OU", "U")
# The height of a position in the graphs of a rack, in inches: 50 servers stay readable
POSITION_HEIGHT = 0.28
# The lowest dpi of the graphs of a rack: their small figures are unreadable at the default 72 of --dpi
RACK_DPI = 200


def rack_position(place: str) -> int | None:
    """The number of a position in a rack, 'U12' or 'OU12' giving 12; None when it is not a number."""
    text = place.strip()
    prefix = next((prefix for prefix in POSITION_PREFIXES if text.upper().startswith(prefix)), "")
    text = text[len(prefix) :].strip()
    return int(text) if text.isascii() and text.isdigit() else None


def rack_positions(location_path: list[str], traces: list[Trace]) -> tuple[dict[str, int] | None, str | None]:
    """The position of each trace of a group, by its name, when the group is a rack: the place holding its
    servers right at their last place. None, with why, when the positions are not numbers; (None, None)
    when the group is not a rack."""
    paths = [trace.get_location().path for trace in traces]  # type: ignore[union-attr]
    if any(len(path) != len(location_path) + 1 for path in paths):
        return None, None
    positions = {trace.get_name(): rack_position(path[-1]) for trace, path in zip(traces, paths)}
    invalid = sorted({path[-1] for path, position in zip(paths, positions.values()) if position is None})
    if invalid:
        return None, f"rack view not rendered, positions not numbers: {', '.join(repr(place) for place in invalid)}"
    return positions, None  # type: ignore[return-value]


@dataclass
class RackMetric:
    """A metric of the servers of a rack: its series of window means, one per server, by a reduction
    of its sensors per window: the mean of its sensors, the hottest one for the air entering the server."""

    name: str
    unit: str
    # The sensors of a server, and how their window means are reduced to one per window
    read: Callable[[Bench], list]
    reduction: Callable
    # Which sensors give it, in the notes of the graphs
    sensors: str
    # The name of a component given by several sensors, like 'CPUs' for the sockets of a server
    plural: str = ""

    def found(self, bench: Bench) -> list:
        """The sensors of the server having windows."""
        return [metric for metric in self.read(bench) if len(metric.get_mean())]

    def series(self, bench: Bench) -> list[float] | None:
        return reduce_windows(self.found(bench), self.reduction)


def reduce_windows(metrics, reduction) -> list[float] | None:
    """The values of several sensors reduced window by window, on the windows they all have."""
    means = [metric.get_mean() for metric in metrics if len(metric.get_mean())]
    if not means:
        return None
    length = min(len(mean) for mean in means)
    return [float(value) for value in reduction(np.array([mean[:length] for mean in means], dtype=float), axis=0)]


def thermal(bench: Bench, family: str) -> list:
    try:
        return list(bench.get_component(MonitoringContextKeys.Thermal, family).values())
    except KeyError:
        return []


# The Redfish PhysicalContext of the air leaving a server
EXHAUST_FAMILY = "Exhaust"


def exhaust(bench: Bench) -> list:
    """The sensors of the air leaving the server: of the Exhaust family, or named so by the BMC in another
    family, like the 'Sys Exhaust' of the SystemBoard of HPE."""
    try:
        families = bench.get_monitoring_metric(MonitoringContextKeys.Thermal)
    except KeyError:
        return []
    return [
        metric
        for family, metrics in families.items()
        if family != CDU_FAMILY
        for name, metric in metrics.items()
        if family == EXHAUST_FAMILY or "exhaust" in name.lower()
    ]


def fans(bench: Bench) -> list:
    try:
        return [
            metric
            for family in bench.get_monitoring_metric(MonitoringContextKeys.Fans).values()
            for metric in family.values()
        ]
    except KeyError:
        return []


def trace_power(bench: Bench) -> list:
    """The power metric given with the trace, like BMC.Server or PDU.<outlet>."""
    try:
        return [
            bench.get_monitoring_metric_by_name(
                MonitoringContextKeys.PowerConsumption, bench.get_trace().get_metric_name()
            )
        ]
    except (KeyError, ValueError):
        return []


# A temperature of a circuit of a CDU, or the delta of a circuit: its name, its window means, if a delta
CduSerie = tuple[str, list[float], bool]


def rack_cdus(benches: list[Bench]) -> list[tuple[str, list[CduSerie]]]:
    """The temperatures of the circuits of each CDU monitored with the servers of the rack, once per CDU:
    its window means of each circuit temperature it reads, by name, each circuit followed by its delta,
    its return minus its supply on the windows having both: the heat it carries."""
    cdus: dict[str, list[CduSerie]] = {}
    for bench in benches:
        for name, data in ((bench.get("monitoring") or {}).get("cdus") or {}).items():
            if name in cdus:
                continue
            circuits: list[CduSerie] = []
            readings = {}
            for key in CIRCUIT_TEMPERATURES:
                definition = data["metrics"].get(key)
                if not definition or definition["unit"] != "Celsius":
                    continue
                readings[key] = data["readings"][key]["mean"]
                values = [value for value in readings[key] if value is not None]
                if values:
                    # The unit tells it is a temperature: 'Primary supply', narrow enough for the cells
                    circuits.append((definition["name"].removesuffix(" temperature"), values, False))
                circuit = key.removesuffix("_return_temperature")
                if circuit != key and f"{circuit}_supply_temperature" in readings:
                    deltas = [
                        back - forth
                        for forth, back in zip(readings[f"{circuit}_supply_temperature"], readings[key])
                        if forth is not None and back is not None
                    ]
                    if deltas:
                        circuits.append((f"{circuit.capitalize()} ΔT", deltas, True))
            if circuits:
                cdus[name] = circuits
    return list(cdus.items())


# The metrics of the servers of a rack, from the front of the servers to their rear, ending with their
# power; the CDUs, shared by the servers, are given once for the rack
RACK_METRICS = [
    RackMetric("Inlet", "°C", lambda bench: thermal(bench, "Intake"), np.max, "the hottest Intake sensor"),
    RackMetric("Fans", "", fans, np.mean, "the mean of the fans"),
    # The mean of the sensors of a component: of its sockets, of its DIMMs or of its GPUs
    RackMetric("CPU", "°C", lambda bench: thermal(bench, "CPU"), np.mean, "the mean of the CPU sensors", "CPUs"),
    RackMetric("Memory", "°C", lambda bench: thermal(bench, "Memory"), np.mean, "the mean of the Memory sensors"),
    RackMetric("GPU", "°C", lambda bench: thermal(bench, GPU_FAMILY), np.mean, "the mean of the GPUs", "GPUs"),
    RackMetric("Exhaust", "°C", exhaust, np.mean, f"the mean of the {EXHAUST_FAMILY} sensors or named exhaust"),
    RackMetric("Power", "W", trace_power, np.max, "the power metric given with each trace"),
]


def sensors_note(rack: Rack, names) -> str:
    """The note telling which sensors give each metric of a graph of a rack, and which power metric."""

    def sensors(name: str) -> str:
        power = f", {', '.join(rack.power_metrics)}" if name == "Power" and rack.power_metrics else ""
        return f"{rack.label(name)}: {rack.metrics[name].sensors}{power}"

    return "Per window:\n    " + ";\n    ".join(sensors(name) for name in names) + "."


@dataclass
class Slot:
    """Where a server is drawn in the rack: the left of its column and its width, as fractions of the width
    of a column, the bottom of its row and its height, in positions."""

    left: float
    width: float
    bottom: float
    height: float

    @property
    def middle(self) -> float:
        return self.bottom + self.height / 2

    @property
    def position(self) -> int:
        """The position at the bottom of the slot."""
        return round(self.bottom + 0.5)


@dataclass
class RackServer:
    name: str
    position: int
    series: dict[str, list[float] | None]
    # Its height and the one of its chassis in positions: 1 when hwbench did not save them
    height: int = 1
    chassis_height: int = 1
    # The number of sensors of each metric
    counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.means = {name: float(np.mean(serie)) for name, serie in self.series.items() if serie}
        self.slot = Slot(0, 1, self.position - 0.5, 1)

    def mean(self, metric: str) -> float | None:
        return self.means.get(metric)


def fans_unit(benches: list[Bench]) -> str:
    """The unit of the fans, as their BMC gives it: percent or RPM."""
    for bench in benches:
        found = fans(bench)
        if found:
            unit = found[0].get_unit()
            return "%" if unit.lower() in ("percent", "%") else unit
    return ""


def by_position(servers: list[RackServer]) -> dict[int, list[RackServer]]:
    positions: dict[int, list[RackServer]] = {}
    for server in servers:
        positions.setdefault(server.position, []).append(server)
    return positions


def place_nodes(position: int, nodes: list[RackServer]) -> int:
    """Places the servers of a position in the height of their chassis from its bottom left, by rows of the
    height of a server: the 4 nodes of 1U of a 2U chassis on 2 rows of 2, a server of 2U alone on both
    positions. The height of the chassis is given back."""
    chassis = max(node.chassis_height for node in nodes)
    rows = max(1, min(len(nodes), chassis // max(node.height for node in nodes)))
    columns = -(-len(nodes) // rows)
    for index, node in enumerate(nodes):
        row, column = divmod(index, columns)
        node.slot = Slot(column / columns, 1 / columns, position - 0.5 + row * chassis / rows, chassis / rows)
    return chassis


@dataclass
class Rack:
    """What the graphs of a rack draw of a benchmark, read once from the traces of its servers."""

    # The benchmark of the first server, describing the one of all of them in the headers
    bench: Bench
    # The servers from the bottom, the nodes of a position in the order of their names
    servers: list[RackServer]
    # The metrics at least one server has, in the order of RACK_METRICS, and their units
    metrics: dict[str, RackMetric]
    units: dict[str, str]
    cdus: list[tuple[str, list[CduSerie]]]
    # The power metrics given with the traces, like BMC.Server
    power_metrics: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.occupied = by_position(self.servers)
        heights = {position: place_nodes(position, nodes) for position, nodes in self.occupied.items()}
        # The positions taken by the servers, the ones above the bottom of the higher chassis included
        self.covered = {position + offset for position, height in heights.items() for offset in range(height)}
        # The positions drawn: from the first of the rack, the empty ones below the servers included
        self.top = max(self.covered)
        # The servers of each row of the rack, by the middle of their row
        self.rows: dict[float, list[RackServer]] = {}
        for server in self.servers:
            self.rows.setdefault(server.slot.middle, []).append(server)

    def counts(self, name: str) -> list[int]:
        """The numbers of sensors of a metric of the servers having it, from the fewest."""
        return sorted({count for server in self.servers if (count := server.counts.get(name, 0))})

    def label(self, name: str) -> str:
        """The name of a metric, plural when a server has several of its component, like 'CPUs'."""
        metric = self.metrics[name]
        return metric.plural if metric.plural and max(self.counts(name), default=0) > 1 else name

    def title(self, name: str) -> str:
        """The name of a metric with its number of sensors per server, when several, and its unit: 'CPUs x2 (°C)',
        'GPUs x4–8 (°C)' when the servers differ, 'Inlet (°C)'."""
        found = self.counts(name)
        count = f" x{found[0]}" + (f"–{found[-1]}" if len(found) > 1 else "") if found and found[-1] > 1 else ""
        unit = f" ({self.units[name]})" if self.units[name] else ""
        return f"{self.label(name)}{count}{unit}"


def load_rack(args, bench_name: str, positions: dict[str, int]) -> Rack:
    """The rack of the servers of the traces, each of their benchmarks loaded once: loading one parses
    all its monitoring."""
    benches = {trace.get_name(): trace.bench(bench_name) for trace in args.traces}
    heights = {trace.get_name(): (trace.get_height(), trace.get_chassis_height()) for trace in args.traces}
    servers = sorted(
        (
            RackServer(
                name,
                positions[name],
                {metric.name: metric.series(bench) for metric in RACK_METRICS},
                *heights[name],
                {metric.name: len(metric.found(bench)) for metric in RACK_METRICS},
            )
            for name, bench in benches.items()
        ),
        key=lambda server: (server.position, server.name),
    )
    metrics = {metric.name: metric for metric in RACK_METRICS if any(server.series[metric.name] for server in servers)}
    units = {
        name: fans_unit(list(benches.values())) if name == "Fans" else metric.unit for name, metric in metrics.items()
    }
    power_metrics = sorted({trace.get_metric_name() for trace in args.traces})
    return Rack(next(iter(benches.values())), servers, metrics, units, rack_cdus(list(benches.values())), power_metrics)


def row_label(servers: list[RackServer]) -> str:
    """The names of the servers of a row of the rack."""
    if len(servers) <= 2:
        return ", ".join(server.name for server in servers)
    return f"{len(servers)} nodes: {servers[0].name} … {servers[-1].name}"


def rack_header(args, kind: str, bench_name: str, bench: Bench) -> str:
    return (
        f"{args.title}\n\n{kind} during {bench_name} benchmark{context_header(args)}{location_header(args)}"
        f"{cdu_header(args)}\n\n{bench.title()}"
    )


# The space between the header of a graph of a rack and what it draws, in inches
HEADER_GAP = 0.4


def center_header(graph, artists: list):
    """Moves the header of a graph of a rack, the title of its first axes centered on them alone, above
    everything the graph draws and centered on it, as the image is cropped around it. The header is given
    back, for render() to keep it in the image."""
    ax = graph.get_ax()
    header = ax.get_title()
    ax.set_title("")
    renderer = graph.fig.canvas.get_renderer()
    box = Bbox.union(
        [axis.get_tightbbox(renderer) for axis in graph.fig.axes]
        + [artist.get_window_extent(renderer) for artist in artists]
    )
    x, y = graph.fig.transFigure.inverted().transform(((box.x0 + box.x1) / 2, box.y1))
    return graph.fig.text(
        x,
        y,
        header,
        ha="center",
        va="bottom",
        fontsize=plt.rcParams["axes.titlesize"],
        transform=graph.fig.transFigure + ScaledTranslation(0, HEADER_GAP, graph.fig.dpi_scale_trans),
    )


def value_text(value: float) -> str:
    """A value in a cell: without decimal from 100, as the watts."""
    return f"{value:.0f}" if value >= 100 else f"{value:.1f}"


def text_color(background) -> str:
    """The color of a text readable on a background: white on the dark ones."""
    red, green, blue, _ = to_rgba(background)
    return "white" if 0.299 * red + 0.587 * green + 0.114 * blue < 0.5 else "black"


def draw_profile(
    axis, metric: RackMetric, servers: list[RackServer], index: int, label: str | None, ranges: bool
) -> None:
    """The values of a metric by position: the mean of the window means of each server, with the violin of its
    windows from its 5th percentile to its 95th, joined by the mean of the nodes of each position, named in
    the legend by the label."""
    color, marker = curve_style(index)
    located = [server for server in servers if server.series[metric.name]]
    y = np.array([server.slot.middle for server in located])
    means = np.array([server.mean(metric.name) for server in located])
    if ranges:
        violins = axis.violinplot(
            [kept_windows(server.series[metric.name]) for server in located],
            positions=y,
            widths=[0.9 * server.slot.height for server in located],
            orientation="horizontal",
            showextrema=False,
        )
        for body in violins["bodies"]:
            body.set_facecolor(color)
            body.set_edgecolor(color)
            body.set_alpha(0.3)
    axis.plot(means, y, linestyle="none", marker=marker, markersize=MARKER_SIZE, color=color)
    # The line breaks at the servers without the metric, like the ones without GPU between ones with
    profile = sorted(
        (row, float(np.mean(means[y == row])) if row in y else np.nan)
        for row in {server.slot.middle for server in servers}
    )
    axis.plot([value for _, value in profile], [position for position, _ in profile], color=color, alpha=0.6)
    if label:
        # The legend gives the line and the marker, as the curves of the other graphs
        axis.plot([], [], color=color, marker=marker, markersize=MARKER_SIZE, label=label)


# The range of the windows of a server: the warm up of a long benchmark makes its lowest windows far
# from the others, the percentiles leave its first ones out
RANGE_PERCENTILES = (5, 95)


def low_window(serie: list[float] | None) -> float:
    return float(np.percentile(serie or [np.nan], RANGE_PERCENTILES[0]))


def high_window(serie: list[float] | None) -> float:
    return float(np.percentile(serie or [np.nan], RANGE_PERCENTILES[1]))


def kept_windows(serie: list[float] | None) -> np.ndarray:
    """The windows of a server from its 5th percentile to its 95th, all of them when they are too few to tell."""
    windows = np.array(serie or [], dtype=float)
    kept = windows[(windows >= low_window(serie)) & (windows <= high_window(serie))]
    return kept if len(kept) > 1 else windows


def profile_graph(args, bench_name: str, rack: Rack, output_dir, kind: str, filename: str):
    """A graph of the profile of a rack, as high as its positions need."""
    top = rack.top
    graph = Graph(
        args,
        rack_header(args, kind, bench_name, rack.bench),
        "",
        "Position",
        output_dir,
        filename,
    )
    graph.fig.set_size_inches(args.width / graph.dpi, max(args.height / graph.dpi, POSITION_HEIGHT * top + 4))
    graph.rotate_xticks = False
    graph.min_dpi = RACK_DPI
    return graph


def profile_positions(axis, rack: Rack, labels: bool) -> None:
    """The rows of a panel of a profile, the empty positions in gray, named by the position at their bottom
    when labels."""
    for position in range(1, rack.top + 1):
        if position not in rack.covered:
            axis.axhspan(position - 0.5, position + 0.5, color="lightgray", alpha=0.4, linewidth=0)
    axis.set_ylim(0.5, rack.top + 0.5)
    ticks = sorted(rack.rows)
    axis.set_yticks(ticks, [f"U{rack.rows[row][0].slot.position}" for row in ticks] if labels else [], fontsize=8)
    axis.grid(which="major", linewidth=0.3)


def profile_server_names(axis, rack: Rack) -> None:
    """The names of the servers right of a panel of a profile, by row."""
    names = axis.twinx()
    names.set_ylim(0.5, rack.top + 0.5)
    ticks = sorted(rack.rows)
    names.set_yticks(ticks, [row_label(rack.rows[row]) for row in ticks], fontsize=8)


STATISTICS = ("min", "mean", "stddev", "max")


def statistics_rows(series: dict[str, np.ndarray]) -> tuple[str, dict[str, str]]:
    """The header of the legend of a profile, naming the statistics right above their columns, and the
    labels of its curves aligned under it."""
    title_length = max(len(name) for name in [*series, "metric"])
    value_length = max(*(get_max_value_string_length(serie) for serie in series.values()), *map(len, STATISTICS))
    header = f"{'metric':{title_length}} [" + "; ".join(f"{name:>{value_length}}" for name in STATISTICS) + "]"
    return header, {
        name: statistics_in_label(name, serie, title_length, value_length) for name, serie in series.items()
    }


# The panels of the profile of the rack: its metrics from the front of the servers to their rear, the CDUs
# left of them
RACK_PANELS = tuple(metric.name for metric in RACK_METRICS)
# The components given each with what cools them, in a profile of its own: the air entering them, the
# fans, the air leaving them and their power
COMPONENTS = ("CPU", "Memory", "GPU")
COMPONENT_PANELS = ("Inlet", "Fans", "<component>", "Exhaust", "Power")
# The cells of the CDUs of a profile: by rows of 3, the supply, the return and the delta of a circuit, below the
# name of the CDU on a row of a third of a cell
CDU_COLUMNS = 3
CDU_TITLE = 1 / 3


def graph_rack_panels(
    args, bench_name: str, output_dir, rack: Rack, names: list[str], kind: str, filename: str, wide=()
) -> int:
    """The profile of the metrics of the servers of a rack, a panel per metric from the front of the servers
    to their rear, with the violin of the windows of each server from its 5th percentile to its 95th, the wide ones twice
    as wide as the others, and the CDUs left of them, below the legend. The panels of the metrics no server has
    are left out."""
    servers, metrics = rack.servers, rack.metrics
    # A wide metric no server has, like the GPUs of a rack without, has no profile
    if any(name not in metrics for name in wide):
        return 0
    names = [name for name in names if name in metrics]
    if not names:
        return 0
    # A color per metric, the same in every profile
    colors = {metric.name: index for index, metric in enumerate(RACK_METRICS)}
    graph = profile_graph(args, bench_name, rack, output_dir, kind, filename)
    ax = graph.get_ax()
    grid = graph.fig.add_gridspec(1, len(names), width_ratios=[2 if name in wide else 1 for name in names])
    ax.set_subplotspec(grid[0])
    panels = [ax] + [graph.fig.add_subplot(grid[index]) for index in range(1, len(names))]
    # The legend names the metrics of the panels, their statistics aligned
    header, labels = statistics_rows(
        {
            rack.title(name): np.array([mean for server in servers if (mean := server.mean(name)) is not None])
            for name in names
        }
    )
    # The header is the first entry of the legend, without a handle, for its columns to be the ones of the labels
    ax.plot([], [], " ", label=header)
    for panel, name in zip(panels, names):
        profile_positions(panel, rack, panel is ax)
        title = rack.title(name)
        draw_profile(panel, metrics[name], servers, colors[name], None, True)
        color, marker = curve_style(colors[name])
        ax.plot([], [], color=color, marker=marker, markersize=MARKER_SIZE, label=labels[title])
        panel.set_xlabel(title)
    profile_server_names(panels[-1], rack)
    # Given to render() as the legends: its tight bounding box only counts them and the axes
    note = ax.annotate(
        sensors_note(rack, names) + "\n"
        "Legend: the statistics of the means of the servers.\n"
        "Per server: the mean of its window means, its violin the distribution of its windows\n"
        "    from its 5th percentile to its 95th.\n"
        "Gray: empty positions."
        + (
            "\nCDUs: the mean of their window means [the coolest window – the hottest];\n"
            "    ΔT: the return of a circuit minus its supply, window by window."
            if rack.cdus
            else ""
        ),
        xy=(0, 0),
        xycoords="axes fraction",
        xytext=(0, -45),
        textcoords="offset points",
        fontsize=9,
        va="top",
    )
    graph.prepare_grid()
    # The first panel being narrow, the legend is placed left of its positions at a fixed distance,
    # not at a fraction of its width as by render()
    graph.needs_legend = False
    offset = ScaledTranslation(-0.8, 0, graph.fig.dpi_scale_trans)
    legend = ax.legend(loc="upper right", bbox_to_anchor=(0, 1), bbox_transform=ax.transAxes + offset)
    cdu_band(graph, panels, rack, legend)
    graph.render(extra_legend=[legend, note, center_header(graph, [legend, note])])
    return 1


def cdu_band(graph, panels: list, rack: Rack, legend):
    """The CDUs left of the panels of a profile, below the legend and as wide as it, on the bottom of the
    panels: per CDU its name above its circuits by rows of CDU_COLUMNS square cells, each the mean of its
    window means with its coolest and hottest windows."""
    if not rack.cdus:
        return
    fig = graph.fig
    width, height = fig.get_size_inches()
    box = legend.get_window_extent(fig.canvas.get_renderer()).transformed(fig.transFigure.inverted())
    # A block per CDU, from the top: its name, then its rows of cells
    blocks = [(name, -(-len(circuits) // CDU_COLUMNS), circuits) for name, circuits in rack.cdus]
    units = sum(CDU_TITLE + rows for _, rows, _ in blocks)
    # Square cells, CDU_COLUMNS of them as wide as the legend
    cell = (box.x1 - box.x0) * width / CDU_COLUMNS
    bottom = panels[0].get_position().y0
    band = fig.add_axes((box.x0, bottom, box.x1 - box.x0, units * cell / height))
    top = units
    for name, rows, circuits in blocks:
        band.text(CDU_COLUMNS / 2, top - CDU_TITLE / 2, f"CDU {name}", ha="center", va="center", fontsize=13)
        top -= CDU_TITLE
        for index, (circuit, values, delta) in enumerate(circuits):
            row, column = divmod(index, CDU_COLUMNS)
            y = top - row - 1
            band.add_patch(
                Rectangle(
                    (column, y), 1, 1, facecolor="lavender" if delta else "aliceblue", edgecolor="white", linewidth=2
                )
            )
            band.text(
                column + 0.5,
                y + 0.5,
                f"{circuit}\n{np.mean(values):.1f} °C\n[{min(values):.1f} – {max(values):.1f}]",
                ha="center",
                va="center",
                fontsize=10,
            )
        top -= rows
    # A thin black frame around the CDUs, their names included
    band.add_patch(Rectangle((0, 0), CDU_COLUMNS, units, fill=False, edgecolor="black", linewidth=1, clip_on=False))
    band.set_xlim(0, CDU_COLUMNS)
    band.set_ylim(0, units)
    band.set_axis_off()


def graph_rack_profile(args, bench_name: str, output_dir, rack: Rack) -> int:
    """The profile of every metric of the servers of the rack."""
    return graph_rack_panels(
        args,
        bench_name,
        output_dir,
        rack,
        list(RACK_PANELS),
        "Profile of the rack",
        f"rack_profile_{bench_name}{place_suffix(args)}",
    )


def graph_rack_component_profiles(args, bench_name: str, output_dir, rack: Rack) -> int:
    """The profile of each component of the servers with what cools it, the component wider."""
    return sum(
        graph_rack_panels(
            args,
            bench_name,
            output_dir,
            rack,
            [component if name == "<component>" else name for name in COMPONENT_PANELS],
            f"Profile of the rack: {component} and its cooling",
            f"rack_profile_{component}_{bench_name}{place_suffix(args)}",
            wide=(component,),
        )
        for component in COMPONENTS
    )


def draw_cdu_row(
    ax, bottom: float, name_width: float, left: float, right: float, name: str, circuits: list[CduSerie], trends: bool
) -> None:
    """A row of two positions of a CDU from its bottom: its name from 0 to name_width, then its circuits side by
    side from left to right, each its name above the mean of its window means, and its coolest and hottest
    windows, or its trend with its 95th percentile window above its 5th."""
    y = bottom + 1.5
    ax.add_patch(Rectangle((0, bottom), name_width, 2, facecolor="whitesmoke", edgecolor="white"))
    ax.text(name_width / 2, y - 0.5, f"CDU {name}", ha="center", va="center", fontsize=8)
    width = (right - left) / len(circuits)
    for index, (circuit, values, delta) in enumerate(circuits):
        x = left + index * width
        ax.add_patch(
            Rectangle(
                (x, bottom), width, 2, facecolor="lavender" if delta else "aliceblue", edgecolor="white", linewidth=1
            )
        )
        if not trends:
            ax.text(
                x + width / 2,
                y - 0.5,
                f"{circuit}\n{np.mean(values):.1f} °C [{min(values):.1f} – {max(values):.1f}]",
                ha="center",
                va="center",
                fontsize=8,
            )
            continue
        # As a server: its name above its mean, its trend on its own scale and its 95th percentile
        # window above its 5th
        ax.text(x + width / 2, y + 0.1, circuit, ha="center", va="center", fontsize=8)
        middle = y - 0.8
        ax.text(x + 0.14 * width, middle, f"{np.mean(values):.1f} °C", ha="center", va="center", fontsize=8)
        if len(values) > 1:
            lowest, highest = min(values), max(values)
            scale = (np.array(values) - lowest) / (highest - lowest) if highest > lowest else np.full(len(values), 0.5)
            ax.plot(
                np.linspace(x + 0.3 * width, x + 0.8 * width, len(values)),
                middle - 0.45 + 0.9 * scale,
                color="black",
                linewidth=0.8,
            )
        for value, offset in ((high_window(values), 0.25), (low_window(values), -0.25)):
            ax.text(x + 0.9 * width, middle + offset, value_text(value), ha="center", va="center", fontsize=6)


def graph_rack_elevation(args, bench_name: str, output_dir, rack: Rack, trends: bool = False) -> int:
    """The rack seen from the front: a row per position, a column per metric, each cell the mean of the
    window means of a server, its color from the coolest server of the column to the hottest. With the
    trends, each cell also draws the window means of the server, on the same scale in a column."""
    servers, top, cdus = rack.servers, rack.top, rack.cdus
    metrics = list(rack.metrics.values())
    if not metrics:
        return 0
    graph = Graph(
        args,
        rack_header(args, "Rack elevation", bench_name, rack.bench),
        "",
        "Position",
        output_dir,
        f"rack_elevation{'_trends' if trends else ''}_{bench_name}{place_suffix(args)}",
    )
    graph.fig.set_size_inches(
        args.width / graph.dpi, max(args.height / graph.dpi, POSITION_HEIGHT * (top + 2 * len(cdus) + 1) + 4)
    )
    graph.rotate_xticks = False
    graph.min_dpi = RACK_DPI
    ax = graph.get_ax()
    cmap = plt.get_cmap("RdYlBu_r")
    # The column of the servers is wider than the ones of the metrics, the names being longer; the
    # metrics go from the front of the servers, told left of the positions, to their rear, told right
    name_width = 2.0
    gap = 0.15
    side = 0.4
    columns = [name_width + gap + index for index in range(len(metrics) + 1)]
    headers = []
    for column, metric in enumerate(metrics):
        means = [mean for server in servers if (mean := server.mean(metric.name)) is not None]
        # A column without differences between its servers has no color to tell
        norm = Normalize(min(means), max(means)) if max(means) > min(means) else None
        windows = [value for server in servers for value in server.series[metric.name] or []]
        lowest, highest = min(windows), max(windows)
        headers.append((columns[column] + 0.5, f"{rack.title(metric.name)}\n{min(means):.1f} – {max(means):.1f}"))
        for server in servers:
            slot = server.slot
            x, width, middle = columns[column] + slot.left, slot.width, slot.middle
            mean = server.mean(metric.name)
            color: Any = (
                cmap(norm(mean)) if mean is not None and norm else "whitesmoke" if mean is not None else "white"
            )
            ax.add_patch(
                Rectangle((x, slot.bottom), width, slot.height, facecolor=color, edgecolor="white", linewidth=1)
            )
            if mean is None:
                continue
            # A server as wide as its column gives its mean left of its trend and its range right of it,
            # its 95th percentile window above its 5th; the narrower nodes give their trends only
            alone = width > 0.5
            text_width = width if not trends else 0.28 * width if alone else 0
            range_width = 0.2 * width if trends and alone else 0
            if text_width:
                ax.text(
                    x + text_width / 2,
                    middle,
                    value_text(mean),
                    ha="center",
                    va="center",
                    fontsize=7 if width < 0.5 else 8,
                    color=text_color(color),
                )
            serie = server.series[metric.name] or []
            if trends and len(serie) > 1:
                left, right = x + text_width + 0.03 * width, x + width - range_width - 0.03 * width
                scale = (
                    (np.array(serie) - lowest) / (highest - lowest) if highest > lowest else np.full(len(serie), 0.5)
                )
                ax.plot(
                    np.linspace(left, right, len(serie)),
                    middle - 0.35 + 0.7 * scale,
                    # Drawn like the figures, white over the dark colors: the cell keeps the color of the column
                    color=text_color(color),
                    linewidth=0.8,
                )
            if range_width and serie:
                for value, offset in ((high_window(serie), 0.22), (low_window(serie), -0.22)):
                    ax.text(
                        x + width - range_width / 2,
                        middle + offset,
                        value_text(value),
                        ha="center",
                        va="center",
                        fontsize=6,
                        color=text_color(color),
                    )
    for position in range(1, top + 1):
        if position not in rack.covered:
            ax.add_patch(
                Rectangle((0, position - 0.5), name_width, 1, facecolor="lightgray", alpha=0.4, edgecolor="white")
            )
            ax.add_patch(
                Rectangle(
                    (columns[0], position - 0.5),
                    columns[-1] - columns[0],
                    1,
                    facecolor="lightgray",
                    alpha=0.4,
                    edgecolor="white",
                )
            )
    for server in servers:
        slot = server.slot
        ax.add_patch(
            Rectangle(
                (slot.left * name_width, slot.bottom),
                slot.width * name_width,
                slot.height,
                facecolor="whitesmoke",
                edgecolor="white",
            )
        )
        ax.text(
            (slot.left + slot.width / 2) * name_width,
            slot.middle,
            server.name,
            ha="center",
            va="center",
            fontsize=6 if slot.width < 0.5 else 8,
        )
    headers.insert(0, (name_width / 2, "Server"))

    # The CDUs below the rack, a row each over the whole width, below a gap of one position
    for row, (name, circuits) in enumerate(cdus):
        draw_cdu_row(ax, -3 - 2 * row, name_width, columns[0], columns[-1], name, circuits, trends)

    ax.set_xlim(0, columns[-1] + side)
    ax.set_ylim(-1 - 2 * len(cdus) if cdus else 0.5, top + 0.5)
    ax.set_xticks([x for x, _ in headers], [text for _, text in headers], fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(range(1, top + 1), [f"U{position}" for position in range(1, top + 1)], fontsize=8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    graph.needs_legend = False
    note = ax.text(
        0,
        -0.5 / (top + 1),
        sensors_note(rack, rack.metrics) + "\n"
        # A line per subject, the longest ones split: a wide note would widen the image
        "Each cell: the mean of the window means of the server.\n"
        "    Colors scaled per column, from its coolest server to its hottest. Gray: empty positions.\n"
        "CDUs: the mean of their window means"
        + ("" if trends else " [the coolest window – the hottest]")
        + ";\n    ΔT: the return of a circuit minus its supply, window by window."
        + (
            "\nCurves: the window means of the server during the benchmark, scaled per column,\n"
            "    from its lowest window to its highest; right of them, its 95th percentile window above its 5th.\n"
            "    The ones of the CDUs on the scale of each of their cells."
            if trends
            else ""
        ),
        transform=ax.transAxes,
        fontsize=9,
        va="top",
    )
    graph.render(extra_legend=[note, center_header(graph, [note])])
    return 1


def graph_rack(args, bench_name: str, output_dir, positions: dict[str, int]) -> int:
    """The graphs of a rack during a benchmark, the benchmark of each server loaded once for all of them."""
    rack = load_rack(args, bench_name, positions)
    return (
        graph_rack_profile(args, bench_name, output_dir, rack)
        + graph_rack_component_profiles(args, bench_name, output_dir, rack)
        + graph_rack_elevation(args, bench_name, output_dir, rack)
        + graph_rack_elevation(args, bench_name, output_dir, rack, trends=True)
    )
