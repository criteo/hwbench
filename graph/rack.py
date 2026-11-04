from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Colormap, LinearSegmentedColormap, Normalize, to_rgba
from matplotlib.patches import Rectangle
from matplotlib.path import Path
from matplotlib.transforms import Bbox, ScaledTranslation, offset_copy

from graph.cdu import CIRCUIT_TEMPERATURES
from graph.common import bench_workers, graph_header
from graph.graph import MARKER_SIZE, Graph, curve_style, get_max_value_string_length, statistics_in_label
from graph.group import place_suffix
from graph.trace import Bench, Trace
from graph.windows import high_window, kept_windows, low_window
from hwbench.bench.monitoring_structs import (
    CDU_FAMILY,
    GPU_FAMILY,
    MonitoringContextKeys,
)
from hwbench.environment.ashrae import FAMILIES as ASHRAE_FAMILIES
from hwbench.environment.ashrae import LIMITS as ASHRAE_LIMITS
from hwbench.environment.ashrae import Limits

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


# The Redfish PhysicalContext of the air entering and leaving a server
INTAKE_FAMILY = "Intake"
EXHAUST_FAMILY = "Exhaust"


def air(bench: Bench, family: str, word: str, others: tuple[str, ...]) -> list:
    """The sensors of the air of the server: of <family>, or named with <word> by the BMC in another family
    than <others>."""
    try:
        families = bench.get_monitoring_metric(MonitoringContextKeys.Thermal)
    except KeyError:
        return []
    return [
        metric
        for name_family, metrics in families.items()
        if name_family not in others
        for name, metric in metrics.items()
        if name_family == family or word in name.lower()
    ]


def inlet(bench: Bench) -> list:
    """The sensors of the air entering the server: of the Intake family or, when the BMC gives none, named
    so in another family, like the 'Inlet Temp' of the SystemBoard of a Dell R6625. Next to an Intake
    sensor, the ones named inlet are inside the server, like the '11-Board Inlet' or the '43-P/S 1 Inlet'
    of HPE; the inlet of a GPU or of a power supply is never the one of the server."""
    return thermal(bench, INTAKE_FAMILY) or air(bench, INTAKE_FAMILY, "inlet", (CDU_FAMILY, GPU_FAMILY, "PowerSupply"))


def exhaust(bench: Bench) -> list:
    """The sensors of the air leaving the server: of the Exhaust family, or named so by the BMC in another
    family, like the 'Sys Exhaust' of the SystemBoard of HPE."""
    return air(bench, EXHAUST_FAMILY, "exhaust", (CDU_FAMILY,))


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
class CduCircuit(NamedTuple):
    """A temperature of a CDU: its name, its window means, if it is the delta of a circuit, and for a supply
    the family of the ASHRAE class limiting it, 'primary' or 'secondary'."""

    name: str
    values: list[float]
    delta: bool = False
    family: str | None = None


def rack_cdus(benches: list[Bench]) -> list[tuple[str, list[CduCircuit]]]:
    """The temperatures of the circuits of each CDU monitored with the servers of the rack, once per CDU:
    its window means of each circuit temperature it reads, by name, each circuit followed by its delta,
    its return minus its supply on the windows having both: the heat it carries."""
    cdus: dict[str, list[CduCircuit]] = {}
    for bench in benches:
        for name, data in ((bench.get("monitoring") or {}).get("cdus") or {}).items():
            if name in cdus:
                continue
            circuits: list[CduCircuit] = []
            readings = {}
            for key in CIRCUIT_TEMPERATURES:
                definition = data["metrics"].get(key)
                if not definition or definition["unit"] != "Celsius":
                    continue
                readings[key] = data["readings"][key]["mean"]
                values = [value for value in readings[key] if value is not None]
                if values:
                    # The unit tells it is a temperature: 'Primary supply', narrow enough for the cells
                    supplied = key.removesuffix("_supply_temperature")
                    family = supplied if supplied != key and supplied in ASHRAE_FAMILIES else None
                    circuits.append(CduCircuit(definition["name"].removesuffix(" temperature"), values, False, family))
                circuit = key.removesuffix("_return_temperature")
                if circuit != key and f"{circuit}_supply_temperature" in readings:
                    deltas = [
                        back - forth
                        for forth, back in zip(readings[f"{circuit}_supply_temperature"], readings[key])
                        if forth is not None and back is not None
                    ]
                    if deltas:
                        circuits.append(CduCircuit(f"{circuit.capitalize()} ΔT", deltas, True))
            if circuits:
                cdus[name] = circuits
    return list(cdus.items())


# The metrics of the servers of a rack, from the front of the servers to their rear, ending with their
# power; the CDUs, shared by the servers, are given once for the rack
RACK_METRICS = [
    RackMetric("Inlet", "°C", inlet, np.max, f"the hottest {INTAKE_FAMILY} sensor, or named inlet without one"),
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
    # The label the topology gives it, and its ASHRAE classes by family
    label: str | None = None
    ashrae: dict[str, str] = field(default_factory=dict)
    # The unit of its fans, as its BMC gives it: percent or RPM
    fans_unit: str = ""
    # How the topology says each of its components is cooled, air or liquid: air when it does not
    cooling: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.means = {name: float(np.mean(serie)) for name, serie in self.series.items() if serie}
        self.slot = Slot(0, 1, self.position - 0.5, 1)

    def mean(self, metric: str) -> float | None:
        return self.means.get(metric)

    def liquid_cooled(self, metric: str) -> bool:
        """Whether the component of a metric, like CPU, is cooled by a liquid."""
        return metric in COMPONENTS and self.cooling.get(metric.lower()) == "liquid"

    def named(self, separator: str = " ") -> str:
        """Its name, followed by its label when it has one."""
        return f"{self.name}{separator}({self.label})" if self.label else self.name

    def unit(self, metric: str, units: dict[str, str]) -> str:
        """The unit of a metric of the server: the one of its fans, or the one of the metric."""
        return self.fans_unit if metric == "Fans" else units.get(metric, "")


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
    cdus: list[tuple[str, list[CduCircuit]]]
    # The power metrics given with the traces, like BMC.Server
    power_metrics: list[str] = field(default_factory=list)
    # The ASHRAE classes of the circuits of each CDU by family
    cdu_ashrae: dict[str, dict[str, str]] = field(default_factory=dict)
    # The numbers of workers of the servers, which differ with their number of cores
    workers: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.occupied = by_position(self.servers)
        heights = {position: place_nodes(position, nodes) for position, nodes in self.occupied.items()}
        # The height of the chassis at each occupied position: its place left by a missing node is empty
        self.chassis = heights
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
    # The classes of --ashrae replace the ones of the traces, family by family
    forced = getattr(args, "ashrae", None) or {}
    classes = {trace.get_name(): trace.get_ashrae() | forced for trace in args.traces}
    labels = {trace.get_name(): trace.get_label() for trace in args.traces}
    cooling = {trace.get_name(): trace.get_cooling() for trace in args.traces}
    servers = sorted(
        (
            RackServer(
                name,
                positions[name],
                {metric.name: metric.series(bench) for metric in RACK_METRICS},
                *heights[name],
                {metric.name: len(metric.found(bench)) for metric in RACK_METRICS},
                labels[name],
                classes[name],
                fans_unit([bench]),
                cooling[name],
            )
            for name, bench in benches.items()
        ),
        key=lambda server: (server.position, server.name),
    )
    # A CDU takes the classes of the first server monitored with it, from the topology, then the ones of its
    # section, then the ones of --ashrae
    cdu_ashrae: dict[str, dict[str, str]] = {}
    for trace in args.traces:
        for name, declared in trace.get_cdu_ashrae().items():
            cdu_ashrae.setdefault(name, trace.get_ashrae() | declared | forced)
    metrics = {metric.name: metric for metric in RACK_METRICS if any(server.series[metric.name] for server in servers)}
    # The fans of a rack mixing BMCs can be in percent for some servers, in RPM for others: all their units
    units = {
        name: ", ".join(sorted({server.fans_unit for server in servers} - {""})) if name == "Fans" else metric.unit
        for name, metric in metrics.items()
    }
    power_metrics = sorted({trace.get_metric_name() for trace in args.traces})
    return Rack(
        next(iter(benches.values())),
        servers,
        metrics,
        units,
        rack_cdus(list(benches.values())),
        power_metrics,
        cdu_ashrae,
        bench_workers(list(benches.values())),
    )


def row_label(servers: list[RackServer]) -> str:
    """The names of the servers of a row of the rack."""
    if len(servers) <= 2:
        return ", ".join(server.named() for server in servers)
    return f"{len(servers)} nodes: {servers[0].name} … {servers[-1].name}"


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


def svg_path(d: str) -> Path:
    """The path of the absolute M, L, H, V, C, S and Z commands of an SVG path, centered on 0 with y up, as a
    marker of matplotlib."""
    tokens = re.findall(r"[MLHVCSZ]|-?[\d.]+", d)
    vertices: list[tuple[float, float]] = []
    codes: list = []
    point = start = (0.0, 0.0)
    control: tuple[float, float] | None = None
    index, command = 0, ""
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command == "Z":
                vertices.append(start)
                codes.append(Path.CLOSEPOLY)
                point, control = start, None
                continue
        count = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4}[command]
        numbers = [float(value) for value in tokens[index : index + count]]
        index += count
        if command == "M":
            point = start = (numbers[0], numbers[1])
            vertices.append(point)
            codes.append(Path.MOVETO)
            # The pairs after the first one of a move are lines
            command, control = "L", None
        elif command in "LHV":
            point = {
                "L": (numbers[0], numbers[-1]),
                "H": (numbers[0], point[1]),
                "V": (point[0], numbers[0]),
            }[command]
            vertices.append(point)
            codes.append(Path.LINETO)
            control = None
        else:
            # S mirrors the second control point of the previous curve
            first = (
                (numbers[0], numbers[1])
                if command == "C"
                else (2 * point[0] - control[0], 2 * point[1] - control[1])
                if control
                else point
            )
            second, end = (numbers[-4], numbers[-3]), (numbers[-2], numbers[-1])
            vertices += [first, second, end]
            codes += [Path.CURVE4] * 3
            point, control = end, second
    xs, ys = [x for x, _ in vertices], [y for _, y in vertices]
    middle = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    return Path([(x - middle[0], middle[1] - y) for x, y in vertices], codes)


# The drop marking a component cooled by a liquid, mdi:water-sync of the Material Design Icons by
# Pictogrammers, Apache License 2.0
WATER_DROP = svg_path(
    "M12 3.2C12 3.2 6 10 6 14C6 17.3 8.7 20 12 20S18 17.3 18 14C18 10 12 3.2 12 3.2M12 8.5V10C14.2 10 16 11.8 16 14"
    "C16 14.8 15.8 15.6 15.3 16.2L14.2 15.1C14.4 14.8 14.5 14.4 14.5 14C14.5 12.6 13.4 11.5 12 11.5V13L9.8 10.8L12 8.5"
    "M8.7 11.8L9.8 12.9C9.6 13.2 9.5 13.6 9.5 14C9.5 15.4 10.6 16.5 12 16.5V15L14.2 17.2L12 19.5V18C9.8 18 8 16.2 8 14"
    "C8 13.2 8.2 12.4 8.7 11.8Z"
)


class Drop(NamedTuple):
    """The drop of a component cooled by a liquid, in the bottom left corner of a cell <height> positions
    high whose mean is written in <fontsize> points, at most <largest> points high."""

    x: float
    y: float
    height: float
    fontsize: float
    largest: float
    color: Any
    cell: Rectangle


# The smallest drop drawn, in points: a smaller one is a dot; and its margin to the borders of its cell, wider
# than the white border of the cell
SMALLEST_DROP = 2.5
DROP_MARGIN = 1.5


def draw_drops(ax, drops: list[Drop]) -> None:
    """The <drops>, once the limits of the axes are set: as high as the room the mean of a cell leaves under
    it, at most their largest size, in points whatever the scale of the axes, in the color of the text of
    their cell and clipped by it."""
    bottom, top = ax.get_ylim()
    figure_height = ax.figure.get_size_inches()[1] * ax.get_position().height * 72
    points = figure_height / (top - bottom)
    for drop in drops:
        size = min(drop.largest, (drop.height * points - drop.fontsize) / 2 - DROP_MARGIN)
        if size < SMALLEST_DROP:
            continue
        ax.plot(
            drop.x,
            drop.y,
            marker=WATER_DROP,
            markersize=size,
            # Without the edge of a marker, which would draw it larger than its size, over the border of the cell
            markeredgewidth=0,
            color=drop.color,
            linestyle="none",
            transform=offset_copy(
                ax.transData, fig=ax.figure, x=size / 2 + DROP_MARGIN, y=size / 2 + DROP_MARGIN, units="points"
            ),
            clip_path=drop.cell,
        )


def text_color(background) -> str:
    """The color of a text readable on a background: white on the dark ones."""
    red, green, blue, _ = to_rgba(background)
    return "white" if 0.299 * red + 0.587 * green + 0.114 * blue < 0.5 else "black"


# The metrics of the air, colored on the allowable range of the ASHRAE air class of each server
AIR_METRICS = ("Inlet", "Exhaust")
# The colors of the cells, from the coolest to the hottest
CELL_COLORMAP = plt.get_cmap("RdYlBu_r")
# The fans and the power are not temperatures: from green, the slowest or the lowest, to red
LOAD_COLORMAP = plt.get_cmap("RdYlGn_r")
LOAD_METRICS = ("Fans", "Power")
# The components: green up to a realistic lowest temperature, then up to red at the hottest, in °C
COMPONENT_TEMPERATURES = (30.0, 100.0)
# The air of a server of an ASHRAE air class: its inlet green on the recommended range of the class, blue
# below, yellow then red above, dark out of the allowable range; its exhaust green up to the maximum of the
# allowable range, then yellow and red from EXHAUST_HOT
EXHAUST_HOT = 60.0
AIR_GREEN = "#a6d96a"
AIR_YELLOW = "#fee08b"
AIR_RED = "#f46d43"
AIR_DARK_RED = "#a50026"
AIR_BLUE = "#74add1"
AIR_DARK_BLUE = "#313695"
# How close to the maximum of its ASHRAE class the hottest window of the supply of a CDU turns it orange, in °C
SUPPLY_MARGIN = 2.0
SUPPLY_COLORS = {"below": "#c7e9c0", "close": "#fdd49e", "above": "#fc9272"}


def exhaust_colormap(limits: Limits) -> tuple[Colormap, Normalize]:
    """The colors of the exhaust of a server of an ASHRAE air class, which limits its inlet only: green on its
    allowable range, then from green to red at EXHAUST_HOT, red above."""
    lowest, highest = limits.allowable
    # The air classes have both bounds
    assert lowest is not None
    assert highest is not None
    green = (highest - lowest) / (EXHAUST_HOT - lowest)
    colors = [(0, AIR_GREEN), (green, AIR_GREEN), ((green + 1) / 2, AIR_YELLOW), (1, AIR_DARK_RED)]
    return LinearSegmentedColormap.from_list("exhaust", colors), Normalize(lowest, EXHAUST_HOT, clip=True)


def inlet_colormap(limits: Limits) -> tuple[Colormap, Normalize]:
    """The colors of the inlet of a server of an ASHRAE air class: green on its recommended range, from blue
    to green below it, from yellow to red above it, dark blue and dark red out of its allowable range."""
    lowest, highest = limits.allowable
    # The air classes have both bounds and a recommended range
    assert lowest is not None
    assert highest is not None
    assert limits.recommended is not None
    low, high = ((bound - lowest) / (highest - lowest) for bound in limits.recommended)
    colors = [(0, AIR_BLUE), (low, AIR_GREEN), (high, AIR_GREEN), ((high + 1) / 2, AIR_YELLOW), (1, AIR_RED)]
    cmap = LinearSegmentedColormap.from_list("inlet", colors)
    cmap.set_under(AIR_DARK_BLUE)
    cmap.set_over(AIR_DARK_RED)
    return cmap, Normalize(lowest, highest)


def curve_bounds(servers: list[RackServer], name: str, units: dict[str, str]) -> dict[str, tuple[float, float]]:
    """The lowest and the highest windows of the servers of a column, by unit: its fans can be in percent for
    some servers, in RPM for others, and a curve in percent would be flat on the scale of the RPM."""
    windows: dict[str, list[float]] = {}
    for server in servers:
        windows.setdefault(server.unit(name, units), []).extend(server.series[name] or [])
    return {unit: (min(values), max(values)) for unit, values in windows.items() if values}


def cell_scale(
    name: str, server: RackServer, unit: str, relative: Normalize | None
) -> tuple[Colormap, Normalize | None]:
    """The colors of a cell and their scale: for a server of an ASHRAE air class, the ones of inlet_colormap()
    and exhaust_colormap(); green to red from 0 to 100 for the fans in percent, and on COMPONENT_TEMPERATURES
    for the components; the relative scale of the column otherwise, from green to red for the fans and the
    power."""
    limits = ASHRAE_LIMITS.get(server.ashrae.get("air", "")) if name in AIR_METRICS else None
    if limits and name == "Exhaust":
        return exhaust_colormap(limits)
    if limits:
        return inlet_colormap(limits)
    if name == "Fans" and unit == "%":
        return LOAD_COLORMAP, Normalize(0, 100)
    if name in COMPONENTS:
        return LOAD_COLORMAP, Normalize(*COMPONENT_TEMPERATURES, clip=True)
    return LOAD_COLORMAP if name in LOAD_METRICS else CELL_COLORMAP, relative


def air_classes_line(servers: list[RackServer], exhaust: bool = False) -> str | None:
    """The ASHRAE air classes of the servers, each with its recommended range and its allowable one,
    'A1: 18–27 [15–32]', or for the exhaust the allowable range in green and the red, 'A1: 15–32, 60 red';
    None when no server has one."""
    names = sorted({name for server in servers if (name := server.ashrae.get("air"))})
    lines = []
    for name in names:
        limits = ASHRAE_LIMITS[name]
        allowable = f"{limits.allowable[0]:g}–{limits.allowable[1]:g}"
        if exhaust:
            lines.append(f"{name}: {allowable}, {EXHAUST_HOT:g} red")
            continue
        recommended = f"{limits.recommended[0]:g}–{limits.recommended[1]:g} " if limits.recommended else ""
        lines.append(f"{name}: {recommended}[{allowable}]")
    return ", ".join(lines) or None


def supply_class(circuit: CduCircuit, classes: dict[str, str]) -> tuple[str, float] | None:
    """The ASHRAE class limiting a supply of a CDU, and its maximum; None without one, or without maximum."""
    name = classes.get(circuit.family or "")
    maximum = ASHRAE_LIMITS[name].allowable[1] if name else None
    return (name, maximum) if name and maximum is not None else None


def circuit_style(circuit: CduCircuit, classes: dict[str, str], separator: str = " ") -> tuple[str, str]:
    """The name of a circuit of a CDU and its color: a supply limited by an ASHRAE class is named after it,
    after the separator, green when its hottest window is below its maximum by more than SUPPLY_MARGIN,
    orange up to it, red above."""
    found = supply_class(circuit, classes)
    if found is None:
        return circuit.name, "lavender" if circuit.delta else "aliceblue"
    name, maximum = found
    hottest = max(circuit.values)
    level = "above" if hottest > maximum else "close" if hottest > maximum - SUPPLY_MARGIN else "below"
    return f"{circuit.name}{separator}{name}", SUPPLY_COLORS[level]


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


def profile_graph(args, bench_name: str, rack: Rack, output_dir, kind: str, filename: str):
    """A graph of the profile of a rack, as high as its positions need."""
    top = rack.top
    graph = Graph(
        args,
        graph_header(args, kind, bench_name, rack.bench, rack.workers),
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
        for index, circuit in enumerate(circuits):
            row, column = divmod(index, CDU_COLUMNS)
            y = top - row - 1
            # The class on its own line, the cells being square
            title, color = circuit_style(circuit, rack.cdu_ashrae.get(name, {}), "\n")
            values = circuit.values
            band.add_patch(Rectangle((column, y), 1, 1, facecolor=color, edgecolor="white", linewidth=2))
            band.text(
                column + 0.5,
                y + 0.5,
                f"{title}\n{np.mean(values):.1f} °C\n[{min(values):.1f} – {max(values):.1f}]",
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
    ax,
    bottom: float,
    name_width: float,
    left: float,
    right: float,
    name: str,
    circuits: list[CduCircuit],
    classes: dict[str, str],
) -> None:
    """A row of two positions of a CDU from its bottom: its name from 0 to name_width, then its circuits side by
    side from left to right, each its name above the mean of its window means, its trend, and its 95th
    percentile window above its 5th."""
    y = bottom + 1.5
    ax.add_patch(Rectangle((0, bottom), name_width, 2, facecolor="whitesmoke", edgecolor="white"))
    ax.text(name_width / 2, y - 0.5, f"CDU {name}", ha="center", va="center", fontsize=8)
    width = (right - left) / len(circuits)
    for index, serie in enumerate(circuits):
        x = left + index * width
        circuit, color = circuit_style(serie, classes)
        values = serie.values
        ax.add_patch(Rectangle((x, bottom), width, 2, facecolor=color, edgecolor="white", linewidth=1))
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


def colors_note(rack: Rack) -> str:
    """The lines of the note of an elevation telling how its cells are colored."""
    lines = []
    air = [name for name in AIR_METRICS if name in rack.metrics]
    classed = [server for server in rack.servers if server.ashrae.get("air")]
    if classed and "Inlet" in rack.metrics:
        lines.append(
            "    Inlet: green on the recommended range of the ASHRAE air class of each server, before its allowable\n"
            "        range in the header; blue below it, yellow to red above it, dark out of the allowable range."
        )
    if classed and "Exhaust" in rack.metrics:
        lines.append(
            "    Exhaust: green on the allowable range of the ASHRAE air class of each server,\n"
            f"        then up to red at {EXHAUST_HOT:g} °C: ASHRAE limits the inlet only."
        )
    if air and len(classed) < len(rack.servers):
        servers = " of the servers without ASHRAE air class" if classed else ""
        lines.append(f"    {', '.join(air)}{servers}: from the coolest server to the hottest.")
    if "Fans" in rack.metrics:
        lines.append(
            "    Fans: from green at 0 % to red at 100 %."
            if rack.units["Fans"] == "%"
            else "    Fans: in %, from green at 0 % to red at 100 %; in RPM, from green, its slowest server, to red, its fastest."
            if "%" in rack.units["Fans"].split(", ")
            else "    Fans: from green, its slowest server, to red, its fastest."
        )
    components = [rack.label(name) for name in COMPONENTS if name in rack.metrics]
    if components:
        lowest, highest = COMPONENT_TEMPERATURES
        lines.append(f"    {', '.join(components)}: green up to {lowest:g} °C, then up to red at {highest:g} °C.")
    if "Power" in rack.metrics:
        lines.append("    Power: from green, its lowest server, to red, its highest.")
    if any(server.liquid_cooled(name) for server in rack.servers for name in rack.metrics):
        lines.append("    A drop, bottom left: a component the topology says cooled by a liquid.")
    return "\n".join([*lines, "    Gray: empty positions, and the metrics a server does not give."]) + "\n"


def supplies_note(rack: Rack) -> str:
    """The lines of the note of an elevation telling how the supplies of the CDUs are colored, when an ASHRAE
    class limits one of them."""
    limited = any(
        supply_class(circuit, rack.cdu_ashrae.get(name, {})) for name, circuits in rack.cdus for circuit in circuits
    )
    if not limited:
        return ""
    return (
        f"\n    Supplies by their hottest window: green below the maximum of their ASHRAE class by more than "
        f"{SUPPLY_MARGIN:g} °C,\n        orange up to it, red above it."
    )


# The gray of the metrics a server does not give, like the memory of a BMC without sensor for it: the one of
# the empty positions, lightgray at 0.4 over white, opaque as a cell is drawn over the gray of its chassis
EMPTY_COLOR = tuple(1 - 0.4 * (1 - channel) for channel in to_rgba("lightgray")[:3])


def graph_rack_elevation(args, bench_name: str, output_dir, rack: Rack) -> int:
    """The rack seen from the front: a row per position, a column per metric, each cell the mean of the
    window means of a server, its color on the scale of its column, see colors_note(), and its window
    means, on the same scale in a column."""
    servers, top, cdus = rack.servers, rack.top, rack.cdus
    metrics = list(rack.metrics.values())
    if not metrics:
        return 0
    graph = Graph(
        args,
        graph_header(args, "Rack elevation", bench_name, rack.bench, rack.workers),
        "",
        "Position",
        output_dir,
        f"rack_elevation_{bench_name}{place_suffix(args)}",
    )
    graph.fig.set_size_inches(
        args.width / graph.dpi, max(args.height / graph.dpi, POSITION_HEIGHT * (top + 2 * len(cdus) + 1) + 4)
    )
    graph.rotate_xticks = False
    graph.min_dpi = RACK_DPI
    ax = graph.get_ax()
    # The column of the servers is wider than the ones of the metrics, the names being longer; the
    # metrics go from the front of the servers, told left of the positions, to their rear, told right
    name_width = 2.0
    gap = 0.15
    side = 0.4
    columns = [name_width + gap + index for index in range(len(metrics) + 1)]
    headers = []
    drops: list[Drop] = []
    # A chassis is gray where no node is, like an empty position: its nodes are drawn over it
    for position, height in rack.chassis.items():
        for left, width in ((0, name_width), (columns[0], columns[-1] - columns[0])):
            ax.add_patch(
                Rectangle((left, position - 0.5), width, height, facecolor="lightgray", alpha=0.4, edgecolor="white")
            )
    for column, metric in enumerate(metrics):
        # The servers of a column by unit, its fans being in percent or in RPM: a scale each
        by_unit: dict[str, list[float]] = {}
        for server in servers:
            if (mean := server.mean(metric.name)) is not None:
                by_unit.setdefault(server.unit(metric.name, rack.units), []).append(mean)
        # A column without differences between its servers has no color to tell, but on a fixed scale
        relatives = {
            unit: Normalize(min(means), max(means)) if max(means) > min(means) else None
            for unit, means in by_unit.items()
        }
        mixed = len(by_unit) > 1
        bounds = curve_bounds(servers, metric.name, rack.units)
        ranges = [
            f"{min(means):.1f} – {max(means):.1f}" + (f" {unit}" if mixed else "")
            for unit, means in sorted(by_unit.items())
        ]
        # A line per unit, two ranges on a line overlapping the next columns
        header = "\n".join([rack.title(metric.name), *ranges])
        classes_line = air_classes_line(servers, metric.name == "Exhaust") if metric.name in AIR_METRICS else None
        headers.append((columns[column] + 0.5, f"{header}\n{classes_line}" if classes_line else header))
        for server in servers:
            slot = server.slot
            x, width, middle = columns[column] + slot.left, slot.width, slot.middle
            mean = server.mean(metric.name)
            unit = server.unit(metric.name, rack.units)
            cmap, norm = cell_scale(metric.name, server, unit, relatives.get(unit))
            color: Any = (
                cmap(norm(mean)) if mean is not None and norm else "whitesmoke" if mean is not None else EMPTY_COLOR
            )
            cell = ax.add_patch(
                Rectangle((x, slot.bottom), width, slot.height, facecolor=color, edgecolor="white", linewidth=1)
            )
            graph.tooltip(cell, server.named())
            if mean is None:
                continue
            # A server as wide as its column gives its mean left of its trend and its range right of it,
            # its 95th percentile window above its 5th; a narrower node than half of it its mean only
            alone = width > 0.5
            # A server as wide as its column gives its mean left of its trend and its range right of it,
            # its 95th percentile window above its 5th; a node of half of it the same, smaller, to leave
            # room to its trend; a narrower one its mean only
            half = not alone and width >= 0.5
            text_width = 0.28 * width if alone else 0.26 * width if half else width
            range_width = 0.2 * width if alone or half else 0
            ax.text(
                x + 0.03 * width if half else x + text_width / 2,
                middle,
                value_text(mean),
                ha="left" if half else "center",
                va="center",
                fontsize=8 if alone else 6 if half else 7,
                color=text_color(color),
            )
            if server.liquid_cooled(metric.name):
                # Below its mean, left of its trend
                fontsize = 8 if alone else 6 if half else 7
                drops.append(Drop(x, slot.bottom, slot.height, fontsize, 9 if alone else 6.5, text_color(color), cell))
            serie = server.series[metric.name] or []
            if len(serie) > 1 and text_width < width:
                left, right = x + text_width + 0.03 * width, x + width - range_width - 0.03 * width
                lowest, highest = bounds[unit]
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
                        fontsize=6 if alone else 4.5,
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
        cell = ax.add_patch(
            Rectangle(
                (slot.left * name_width, slot.bottom),
                slot.width * name_width,
                slot.height,
                facecolor="whitesmoke",
                edgecolor="white",
            )
        )
        graph.tooltip(cell, server.named())
        # A node sharing its row with others, even half of it, gets its label under its name, smaller, and
        # its text is cut at its cell: it overlapped its neighbour and the positions of the rack
        shared = slot.width < 1
        ax.text(
            (slot.left + slot.width / 2) * name_width,
            slot.middle,
            server.named("\n" if shared else " "),
            ha="center",
            va="center",
            fontsize=6 if shared else 8,
            clip_path=cell,
            clip_on=True,
        )
    headers.insert(0, (name_width / 2, "Server"))

    # The CDUs below the rack, a row each over the whole width, below a gap of one position
    for row, (name, circuits) in enumerate(cdus):
        draw_cdu_row(
            ax, -3 - 2 * row, name_width, columns[0], columns[-1], name, circuits, rack.cdu_ashrae.get(name, {})
        )

    ax.set_xlim(0, columns[-1] + side)
    ax.set_ylim(-1 - 2 * len(cdus) if cdus else 0.5, top + 0.5)
    draw_drops(ax, drops)
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
        + colors_note(rack)
        + "CDUs: the mean of their window means"
        + ";\n    ΔT: the return of a circuit minus its supply, window by window."
        + supplies_note(rack)
        + "\nCurves: the window means of the server during the benchmark, scaled per column and unit,\n"
        "    from its lowest window to its highest; right of them, its 95th percentile window above its 5th.\n"
        "    The ones of the CDUs on the scale of each of their cells.",
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
    )


# The width of a metric of a rack in the elevation of several racks, and the gap between two racks, in inches
RACKS_METRIC_WIDTH = 0.42
RACKS_GAP = 0.6
# The height of the row of a CDU below a rack, in positions, its circuits 2 positions high
RACKS_CDU_ROW = 2.8


def load_racks(args, bench_name: str, racks: list[tuple[str, list[Trace], dict[str, int]]]) -> list[tuple[str, Rack]]:
    """The racks of a place, each named and loaded from its traces, forgotten once read: a place can hold the
    servers of a whole room."""
    loaded = []
    for name, traces, positions in racks:
        rack_args = copy.copy(args)
        rack_args.traces = traces
        loaded.append((name, load_rack(rack_args, bench_name, positions)))
        for trace in traces:
            trace.forget_content()
    return loaded


def graph_racks_elevation(args, bench_name: str, output_dir, racks: list[tuple[str, Rack]]) -> int:
    """The racks of a place side by side, each seen from the front without names nor trends: a row per position,
    a thin column per metric, each cell the mean of the window means of a server colored as in the rack
    elevations, the relative scales shared by all the racks to compare them."""
    metrics = [metric for metric in RACK_METRICS if any(metric.name in rack.metrics for _, rack in racks)]
    if len(racks) < 2 or not metrics:
        return 0
    # The units of a metric over all the racks: the fans of some can be in percent, the ones of others in RPM
    units = {
        metric.name: ", ".join(
            sorted({unit for _, rack in racks for unit in rack.units.get(metric.name, "").split(", ") if unit})
        )
        for metric in metrics
    }
    # The relative scale of each metric, by unit, over all the racks
    relatives: dict[tuple[str, str], Normalize | None] = {}
    for metric in metrics:
        by_unit: dict[str, list[float]] = {}
        for _, rack in racks:
            for server in rack.servers:
                if (mean := server.mean(metric.name)) is not None:
                    by_unit.setdefault(server.unit(metric.name, rack.units), []).append(mean)
        for unit, means in by_unit.items():
            relatives[(metric.name, unit)] = Normalize(min(means), max(means)) if max(means) > min(means) else None
    # The title of each column with its unit, like 'Fans (%, RPM)'
    titles = {
        metric.name: f"{metric.name} ({units[metric.name]})" if units[metric.name] else metric.name
        for metric in metrics
    }
    top = max(rack.top for _, rack in racks)
    workers = sorted({workers for _, rack in racks for workers in rack.workers})
    graph = Graph(
        args,
        graph_header(args, "Racks elevation", bench_name, racks[0][1].bench, workers),
        "",
        "Position",
        output_dir,
        f"racks_elevation_{bench_name}{place_suffix(args)}",
    )
    width = len(metrics) * RACKS_METRIC_WIDTH
    graph.fig.set_size_inches(
        max(args.width / graph.dpi, len(racks) * (width + RACKS_GAP) + 2),
        POSITION_HEIGHT * (top + 4 + RACKS_CDU_ROW * max(len(rack.cdus) for _, rack in racks)) + 3,
    )
    graph.rotate_xticks = False
    graph.min_dpi = RACK_DPI
    ax = graph.get_ax()
    # A rack is len(metrics) columns of 1, then a gap: the metrics of a rack read from its front to its rear
    gap = RACKS_GAP / RACKS_METRIC_WIDTH
    ticks = []
    drops: list[Drop] = []
    for index, (name, rack) in enumerate(racks):
        left = index * (len(metrics) + gap)
        ax.text(left + len(metrics) / 2, top + 1.6, name, ha="center", va="bottom", fontsize=8, fontweight="bold")
        ticks += [(left + column + 0.5, titles[metric.name]) for column, metric in enumerate(metrics)]
        # The empty positions, and the places of a chassis without node, gray under the servers
        for position in range(1, top + 1):
            if position not in rack.covered:
                ax.add_patch(
                    Rectangle((left, position - 0.5), len(metrics), 1, facecolor=EMPTY_COLOR, edgecolor="white")
                )
        for position, height in rack.chassis.items():
            ax.add_patch(
                Rectangle((left, position - 0.5), len(metrics), height, facecolor=EMPTY_COLOR, edgecolor="white")
            )
        for server in rack.servers:
            slot = server.slot
            for column, metric in enumerate(metrics):
                x = left + column + slot.left
                mean = server.mean(metric.name)
                unit = server.unit(metric.name, rack.units)
                cmap, norm = cell_scale(metric.name, server, unit, relatives.get((metric.name, unit)))
                color: Any = (
                    cmap(norm(mean)) if mean is not None and norm else "whitesmoke" if mean is not None else EMPTY_COLOR
                )
                cell = ax.add_patch(
                    Rectangle(
                        (x, slot.bottom), slot.width, slot.height, facecolor=color, edgecolor="white", linewidth=0.5
                    )
                )
                graph.tooltip(cell, server.named())
                if mean is not None:
                    ax.text(
                        x + slot.width / 2,
                        slot.middle,
                        value_text(mean),
                        ha="center",
                        va="center",
                        fontsize=4.5 if slot.width < 1 else 5.5,
                        color=text_color(color),
                        clip_path=cell,
                        clip_on=True,
                    )
                if mean is not None and server.liquid_cooled(metric.name):
                    fontsize = 4.5 if slot.width < 1 else 5.5
                    largest = 3.5 if slot.width < 1 else 4.5
                    drops.append(Drop(x, slot.bottom, slot.height, fontsize, largest, text_color(color), cell))
    # The CDUs monitored with the servers of each rack below it, a row each: their circuits side by side,
    # colored as below a rack elevation, with the mean of their window means
    cdu_rows = max(len(rack.cdus) for _, rack in racks)
    for index, (_, rack) in enumerate(racks):
        left = index * (len(metrics) + gap)
        for row, (name, circuits) in enumerate(rack.cdus):
            bottom = -RACKS_CDU_ROW * (row + 1) + 0.2
            width = len(metrics) / len(circuits)
            for column, circuit in enumerate(circuits):
                title, color = circuit_style(circuit, rack.cdu_ashrae.get(name, {}), "\n")
                # A word a line: the cells of a circuit are as narrow as a metric
                title = title.replace(" ", "\n")
                cell = ax.add_patch(
                    Rectangle(
                        (left + column * width, bottom), width, 2, facecolor=color, edgecolor="white", linewidth=0.5
                    )
                )
                # The temperatures of the circuits on the same line, below the middle of the cells, their names
                # of two or three lines above them
                center = left + (column + 0.5) * width
                for text, y, va in (
                    (title, bottom + 1.05, "bottom"),
                    (f"{np.mean(circuit.values):.1f} °C", bottom + 0.75, "center"),
                ):
                    ax.text(
                        center,
                        y,
                        text,
                        ha="center",
                        va=va,
                        multialignment="center",
                        fontsize=4,
                        clip_path=cell,
                        clip_on=True,
                    )
            ax.text(left + len(metrics) / 2, bottom - 0.15, f"CDU {name}", ha="center", va="top", fontsize=5)
    ax.set_xlim(-0.2, len(racks) * (len(metrics) + gap) - gap + 0.2)
    ax.set_ylim(0.4 - RACKS_CDU_ROW * cdu_rows - (0.6 if cdu_rows else 0), top + 2.6)
    draw_drops(ax, drops)
    ax.set_xticks([x for x, _ in ticks], [label for _, label in ticks], fontsize=6, rotation=90)
    ax.xaxis.tick_top()
    ax.set_yticks(range(1, top + 1), [f"U{position}" for position in range(1, top + 1)], fontsize=6)
    ax.tick_params(length=0)
    # The positions on both sides, with their title: the racks of a place are too wide to read the ones of the
    # last from the left
    right = ax.secondary_yaxis("right")
    right.set_yticks(range(1, top + 1), [f"U{position}" for position in range(1, top + 1)], fontsize=6)
    right.set_ylabel("Position")
    right.tick_params(length=0)
    right.spines["right"].set_visible(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    graph.needs_legend = False
    note = ax.text(
        0,
        -0.5 / (top + 3),
        f"Columns of each rack, from the front of the servers to their rear: {', '.join(titles.values())}.\n"
        "Each cell: the mean of the window means of the server, colored as in the rack elevations,\n"
        f"    the scales from a server to another shared by the {len(racks)} racks of the place, and by unit for the fans.\n"
        "Gray: empty positions, and the metrics a server does not give.\n"
        + (
            "A drop, bottom left: a component the topology says cooled by a liquid.\n"
            if any(
                server.liquid_cooled(metric.name) for _, rack in racks for server in rack.servers for metric in metrics
            )
            else ""
        )
        + "CDUs below each rack: the mean of the window means of their circuits, colored as below a rack elevation.",
        transform=ax.transAxes,
        fontsize=7,
        va="top",
    )
    graph.render(extra_legend=[note, center_header(graph, [note])])
    return 1


def graph_racks(args, bench_name: str, output_dir, racks: list[tuple[str, list[Trace], dict[str, int]]]) -> int:
    """The elevation of the racks of a place holding several of them."""
    return graph_racks_elevation(args, bench_name, output_dir, load_racks(args, bench_name, racks))
