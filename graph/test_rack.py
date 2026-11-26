from __future__ import annotations

import importlib.util
import json
import pathlib
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.colors import Normalize, to_rgba

from graph.common import graph_header
from graph.rack import (
    AIR_DARK_BLUE,
    AIR_DARK_RED,
    AIR_GREEN,
    RACK_METRICS,
    SUPPLY_COLORS,
    CduCircuit,
    Rack,
    RackServer,
    Slot,
    air_classes_line,
    cell_scale,
    circuit_style,
    colors_note,
    exhaust,
    graph_rack,
    graph_racks,
    inlet,
    load_rack,
    rack_cdus,
    rack_position,
    rack_positions,
    reduce_windows,
    row_label,
    sensors_note,
    statistics_rows,
    text_color,
    value_text,
)
from graph.test_trace import LOCATION, PATH, located_trace
from graph.trace import Trace
from graph.windows import high_window, kept_windows, low_window
from hwbench.bench.monitoring_structs import MonitoringContextKeys

TRACES = pathlib.Path("documentation/example/traces")


@pytest.mark.parametrize(
    ("place", "position"),
    [("12", 12), ("U12", 12), ("OU12", 12), ("u 7", 7), (" 3 ", 3), ("A", None), ("U", None), ("12a", None)],
)
def test_rack_position(place, position):
    """A position is a number, after the U of a 19" rack or the OU of an OCP one."""
    assert rack_position(place) == position


def traces_at(*places: str, depth: int = 0) -> list[Trace]:
    """A trace per place of the rack A12, named after its place, depth levels lower."""
    traces = []
    for place in places:
        trace = located_trace(LOCATION | {"path": [*PATH[:-1], place, *["x"] * depth]})
        trace.logical_name = f"server-{place}"
        traces.append(trace)
    return traces


def test_rack_positions():
    """A group holding its servers right at their last place is a rack, when its places are numbers."""
    rack = PATH[:-1]
    assert rack_positions(rack, traces_at("U1", "OU2", "3")) == ({"server-U1": 1, "server-OU2": 2, "server-3": 3}, None)
    assert rack_positions(rack, traces_at("U1", "A", "B")) == (
        None,
        "rack view not rendered, positions not numbers: 'A', 'B'",
    )
    # A group of racks, its servers two levels lower, is not a rack
    assert rack_positions(rack, traces_at("U1", "U2", depth=1)) == (None, None)


def test_bold_without_cursive(caplog):
    """A title in bold loads only fonts the servers have: no warning about the missing cursive one."""
    import matplotlib.pyplot as plt

    from graph.common import bold
    from graph.graph import init_matplotlib

    backend = plt.get_backend()
    try:
        init_matplotlib(SimpleNamespace(engine="agg"))
        figure = plt.figure()
        figure.suptitle(f"Location: {bold('Cage 1')}")
        figure.canvas.draw()
        plt.close(figure)
    finally:
        plt.rcdefaults()
        plt.switch_backend(backend)
    assert "cursive" not in caplog.text


def windows(*means: list[float]):
    return [SimpleNamespace(get_mean=lambda values=values: values) for values in means]


def test_reduce_windows():
    """The sensors are reduced window by window, on the windows they all have."""
    assert reduce_windows(windows([1, 5, 3], [4, 2]), np.max) == [4, 5]
    assert reduce_windows(windows([1, 5], [3, 3]), np.mean) == [2, 4]
    assert reduce_windows(windows([], []), np.max) is None
    assert reduce_windows([], np.max) is None


def test_curve_bounds_per_unit():
    """The curves of a column are scaled per unit: the fans of a rack mixing BMCs, in percent for some servers and in
    RPM for others, keep curves in percent that are not flat on the scale of the RPM."""
    from graph.rack import curve_bounds

    servers = [
        RackServer("percent", 1, {"Fans": [40.0, 56.0], "Power": [800.0, 900.0]}, fans_unit="%"),
        RackServer("rpm", 2, {"Fans": [9300.0, 10700.0], "Power": [1000.0, 1100.0]}, fans_unit="RPM"),
        RackServer("unknown", 3, {"Fans": None, "Power": None}, fans_unit="RPM"),
    ]
    units = {"Power": "W"}
    assert curve_bounds(servers, "Fans", units) == {"%": (40.0, 56.0), "RPM": (9300.0, 10700.0)}
    assert curve_bounds(servers, "Power", units) == {"W": (800.0, 1100.0)}


class Monitoring:
    """A benchmark giving its thermal families, and the monitoring of its CDUs."""

    def __init__(self, thermal: dict | None = None, cdus: dict | None = None):
        self.thermal, self.cdus = thermal or {}, cdus

    def get_monitoring_metric(self, context):
        assert context == MonitoringContextKeys.Thermal
        return self.thermal

    def get_component(self, context, family):
        return self.get_monitoring_metric(context)[family]

    def get(self, key):
        return {"cdus": self.cdus} if key == "monitoring" and self.cdus is not None else None


def test_exhaust():
    """The air leaving a server: the Exhaust family, or the sensors named so in another, not the ones of a CDU."""
    bench = Monitoring(
        {
            "Exhaust": {"Outlet 1": "outlet"},
            "SystemBoard": {"39-Sys Exhaust 1": "hpe", "22-BMC": "bmc"},
            "CDU": {"CDU exhaust": "cdu"},
        }
    )
    assert exhaust(bench) == ["outlet", "hpe"]


def test_inlet():
    """The air entering a server: the Intake family; without one, the sensors named so in another family,
    like the Inlet Temp of the SystemBoard of a Dell R6625, not the inlet of a GPU, a power supply or a CDU."""
    hpe = Monitoring(
        {
            "Intake": {"01-Inlet Ambient": "ambient"},
            "SystemBoard": {"11-Board Inlet": "board"},
            "PowerSupply": {"43-P/S 1 Inlet": "psu"},
        }
    )
    assert inlet(hpe) == ["ambient"]
    dell = Monitoring(
        {
            "SystemBoard": {"Inlet Temp": "dell", "System Board Exhaust Temp": "exhaust"},
            "PowerSupply": {"PS1 Inlet": "psu"},
            "GPU": {"BMC_GPU_GPU1 Inlet Temp": "gpu"},
            "CDU": {"CDU inlet": "cdu"},
        }
    )
    assert inlet(dell) == ["dell"]


def cdu(readings: dict[str, list[float | None]], unit: str = "Celsius") -> dict:
    return {
        "metrics": {key: {"name": key.replace("_", " ").capitalize(), "unit": unit} for key in readings},
        "readings": {key: {"mean": values} for key, values in readings.items()},
    }


def test_rack_cdus():
    """The temperatures of the circuits of each CDU, once per CDU, each circuit followed by its delta."""
    loop = cdu(
        {
            "primary_supply_temperature": [18.0, None, 18.5],
            "primary_return_temperature": [24.0, 24.5, None],
            "secondary_supply_temperature": [28.0, 28.0, 28.0],
            "secondary_return_temperature": [34.0, 35.0, 36.0],
        }
    )
    benches = [Monitoring(cdus={"cdu-1": loop}), Monitoring(cdus={"cdu-1": loop}), Monitoring()]
    assert rack_cdus(benches) == [
        (
            "cdu-1",
            [
                # A supply with the family of the ASHRAE class limiting it
                CduCircuit("Primary supply", [18.0, 18.5], False, "primary"),
                CduCircuit("Primary return", [24.0, 24.5]),
                # On the windows having both
                CduCircuit("Primary ΔT", [6.0], True),
                CduCircuit("Secondary supply", [28.0, 28.0, 28.0], False, "secondary"),
                CduCircuit("Secondary return", [34.0, 35.0, 36.0]),
                CduCircuit("Secondary ΔT", [6.0, 7.0, 8.0], True),
            ],
        )
    ]
    # Only the temperatures, and a return without its supply has no delta
    assert rack_cdus([Monitoring(cdus={"cdu-2": cdu({"primary_supply_temperature": [1.0]}, "Bar")})]) == []
    assert rack_cdus([Monitoring(cdus={"cdu-3": cdu({"primary_return_temperature": [24.0]})})]) == [
        ("cdu-3", [CduCircuit("Primary return", [24.0])])
    ]


def servers(*specs: tuple[str, int, int, int]) -> Rack:
    """A rack of servers by name, position, height and height of their chassis."""
    rack_servers = [RackServer(name, position, {}, height, chassis) for name, position, height, chassis in specs]
    # The layout does not read the benchmark
    return Rack(None, rack_servers, {}, {}, [])  # type: ignore[arg-type]


def test_rack_layout():
    """The servers of a position fill the height of their chassis by rows of their own height."""
    rack = servers(
        ("node-1", 20, 1, 2), ("node-2", 20, 1, 2), ("node-3", 20, 1, 2), ("node-4", 20, 1, 2), ("big", 30, 2, 2)
    )
    slots = {server.name: server.slot for server in rack.servers}
    # The 4 nodes of 1U of a 2U chassis: 2 rows of 2, from the bottom left
    assert slots["node-1"] == Slot(0, 0.5, 19.5, 1)
    assert slots["node-2"] == Slot(0.5, 0.5, 19.5, 1)
    assert slots["node-4"] == Slot(0.5, 0.5, 20.5, 1)
    assert slots["node-4"].position == 21
    # A 2U server alone on both positions
    assert slots["big"] == Slot(0, 1, 29.5, 2)
    assert rack.covered == {20, 21, 30, 31}
    assert rack.top == 31
    assert [row_label(rack.rows[row]) for row in sorted(rack.rows)] == ["node-1, node-2", "node-3, node-4", "big"]


def test_rack_layout_without_heights():
    """Without the heights in the traces, the servers of a position share a single one."""
    rack = servers(*((f"node-{index}", 5, 1, 1) for index in range(1, 5)))
    assert [server.slot for server in rack.servers] == [Slot(index / 4, 0.25, 4.5, 1) for index in range(4)]
    assert rack.covered == {5}
    assert row_label(rack.servers) == "4 nodes: node-1 … node-4"


def test_statistics_rows():
    """The header of the legend names each statistic right above its column."""
    header, labels = statistics_rows({"Inlet (°C)": np.array([23.0, 29.2]), "Power (W)": np.array([1341.2, 1529.9])})
    for label in labels.values():
        assert len(label) == len(header)
        assert [index for index, char in enumerate(label) if char in "[;]"] == [
            index for index, char in enumerate(header) if char in "[;]"
        ]
    assert header.split("[")[1] == "   min;   mean; stddev;    max]"


def test_sensors_note():
    """The note names the sensors of the metrics drawn, one per line, a component of several sensors in plural."""
    metrics = {metric.name: metric for metric in RACK_METRICS}
    servers = [
        RackServer("server-1", 1, {}, counts={"Inlet": 1, "CPU": 2, "GPU": 0, "Power": 1}),
        RackServer("server-2", 2, {}, counts={"Inlet": 1, "CPU": 2, "GPU": 4, "Power": 1}),
        RackServer("server-3", 3, {}, counts={"Inlet": 1, "CPU": 1, "GPU": 8, "Power": 1}),
    ]
    units = {name: metric.unit for name, metric in metrics.items()}
    rack = Rack(None, servers, metrics, units, [], ["BMC.Server"])  # type: ignore[arg-type]
    assert sensors_note(rack, ["Inlet", "CPU", "Power"]) == (
        "Per window:\n    Inlet: the hottest Intake sensor, or named inlet without one;\n    CPUs: the mean of the CPU sensors;\n"
        "    Power: the power metric given with each trace, BMC.Server."
    )
    # The number of sensors per server in the titles, when several, as a range when the servers differ
    assert [rack.title(name) for name in ("Inlet", "CPU", "GPU", "Power")] == [
        "Inlet (°C)",
        "CPUs x1–2 (°C)",
        "GPUs x4–8 (°C)",
        "Power (W)",
    ]


class Components:
    """A benchmark giving the thermal sensors of its families."""

    def __init__(self, families: dict[str, list[list[float]]]):
        self.families = families

    def get_component(self, context, family):
        assert context == MonitoringContextKeys.Thermal
        return {f"{family} {index}": sensor for index, sensor in enumerate(windows(*self.families[family]))}

    def get_monitoring_metric(self, context):
        assert context == MonitoringContextKeys.Thermal
        return {family: self.get_component(context, family) for family in self.families}


def test_metrics_of_the_sensors():
    """The metrics give the mean of their sensors, the air entering a server its hottest sensor."""
    metrics = {metric.name: metric for metric in RACK_METRICS}
    bench = Components(
        {"CPU": [[50, 60], [70, 80]], "GPU": [[60, 60], [70, 70], [80, 90]], "Intake": [[20, 25], [22, 21]]}
    )
    assert metrics["CPU"].series(bench) == [60, 70]
    assert metrics["GPU"].series(bench) == [70, 220 / 3]
    assert metrics["Inlet"].series(bench) == [22, 25]


def test_windows_and_cells():
    serie = [float(value) for value in range(101)]
    assert (low_window(serie), high_window(serie)) == (5, 95)
    # The violin of a server leaves out its 5% lowest and highest windows, unless too few remain
    assert list(kept_windows(serie)) == list(range(5, 96))
    assert list(kept_windows([1.0, 9.0])) == [1.0, 9.0]
    assert np.isnan(low_window(None))
    assert (value_text(28.46), value_text(1404.4)) == ("28.5", "1404")
    assert (text_color("white"), text_color("black")) == ("black", "white")


def test_graph_rack(tmp_path):
    """The graphs of a rack of the servers of the reference dataset, a 2U chassis of 4 nodes among them."""
    result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
    traces, positions = [], {}
    for name, position, height, chassis in [
        ("server-1", 1, 1, 1),
        *((f"node-{index}", 3, 1, 2) for index in range(1, 5)),
        ("server-5", 6, 2, 2),
    ]:
        result["hardware"]["dmi"] |= {"height": height, "chassis": {"serial": name, "height": chassis}}
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), name, "BMC.Server"))
        positions[name] = position
    args = SimpleNamespace(
        width=1920, height=1080, title="", format="png", engine="cairo", dpi=72, verbose=False, events=[], traces=traces
    )
    # The profiles of the rack, of its CPU and of its memory, without GPU, and the elevation with the trends
    assert graph_rack(args, "cpu_17", tmp_path, positions) == 4
    assert sorted(path.name for path in tmp_path.glob("rack_*.png")) == [
        "rack_elevation_cpu_17.png",
        "rack_profile_CPU_cpu_17.png",
        "rack_profile_Memory_cpu_17.png",
        "rack_profile_cpu_17.png",
    ]


def test_liquid_cooled(tmp_path):
    """The components the topology says cooled by a liquid get a drop, told in the note of the elevation."""
    result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
    result["location"] = {"path": ["A12", "1"], "cooling": {"cpu": "liquid", "memory": "air", "gpu": "air"}}
    path = tmp_path / "server.json"
    path.write_text(json.dumps(result))
    args = SimpleNamespace(
        width=1920,
        height=1080,
        title="",
        format="png",
        engine="cairo",
        dpi=72,
        verbose=False,
        events=[],
        traces=[Trace(str(path), "server", "BMC.Server")],
    )
    rack = load_rack(args, "cpu_17", {"server": 1})
    [server] = rack.servers
    assert server.liquid_cooled("CPU")
    assert not server.liquid_cooled("Memory")
    # Not a component: the power of the server is not cooled
    assert not server.liquid_cooled("Power")
    assert "A drop, bottom left: a component the topology says cooled by a liquid." in colors_note(rack)
    assert not RackServer("air", 2, {}).liquid_cooled("CPU")
    assert graph_rack(args, "cpu_17", tmp_path, {"server": 1}) == 4


@pytest.mark.render
def test_svg_tooltips(tmp_path):
    """In SVG, the mouse over a cell of the elevation tells its server and its label."""
    result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
    result["location"] = {"path": ["A12", "1"], "label": "db-01"}
    path = tmp_path / "server.json"
    path.write_text(json.dumps(result))
    args = SimpleNamespace(
        width=1920,
        height=1080,
        title="",
        format="svg",
        engine="cairo",
        dpi=72,
        verbose=False,
        events=[],
        traces=[Trace(str(path), "server", "BMC.Server")],
    )
    # The cell of its name, and one per metric
    cells = 1 + len(load_rack(args, "cpu_17", {"server": 1}).metrics)
    # The default backend of the tests, then cairo, the default engine of hwgraph, whose SVG has no id of the
    # artists, when it is installed: it comes with the graph extra
    backends = [plt.get_backend()] + (["cairo"] if importlib.util.find_spec("cairo") else [])
    backend = plt.get_backend()
    try:
        for engine in backends:
            plt.switch_backend(engine)
            graph_rack(args, "cpu_17", tmp_path, {"server": 1})
            svg = tmp_path.joinpath("rack_elevation_cpu_17.svg").read_text()
            assert svg.count("<title>server (db-01)</title>") == cells, engine
    finally:
        plt.switch_backend(backend)


def test_rack_power_of_the_traces(tmp_path):
    """The power of a server is the power metric given with its trace, not always the one of the BMC."""
    path = tmp_path / "server.json"
    path.write_text(TRACES.joinpath("cdu_comparison.json").read_text())
    trace = Trace(str(path), "server", "CPU.package")
    rack = load_rack(SimpleNamespace(traces=[trace]), "cpu_17", {"server": 1})
    package = trace.bench("cpu_17").get_monitoring_metric_by_name(MonitoringContextKeys.PowerConsumption, "CPU.package")
    assert rack.servers[0].series["Power"] == [float(value) for value in package.get_mean()]
    assert rack.power_metrics == ["CPU.package"]


def test_ashrae_of_the_rack(tmp_path):
    """--ashrae replaces the classes of the traces; a CDU takes the ones of the topology, then of its section."""
    result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
    result["location"] = {"path": ["PA3", "A12", "1"], "label": "db-01", "ashrae": {"air": "A2", "secondary": "S40"}}
    result["hardware"]["cdu"]["CDU_example"]["ashrae"] = {"secondary": "S30"}
    path = tmp_path / "server.json"
    path.write_text(json.dumps(result))
    args = SimpleNamespace(traces=[Trace(str(path), "server", "BMC.Server")], ashrae={"air": "H1"})
    rack = load_rack(args, "cpu_17", {"server": 1})
    assert rack.servers[0].ashrae == {"air": "H1", "secondary": "S40"}
    assert rack.servers[0].named() == "server (db-01)"
    assert rack.cdu_ashrae == {"CDU_example": {"air": "H1", "secondary": "S30"}}


def test_cell_scale():
    """The inlet on the allowable range of the class of the server, the fans in percent from 0 to 100."""
    relative = Normalize(20, 21)
    classed, unclassed = RackServer("a", 1, {}, ashrae={"air": "A1"}), RackServer("b", 2, {})
    norm = cell_scale("Inlet", classed, "°C", relative)[1]
    assert (norm.vmin, norm.vmax) == (15, 32)
    assert cell_scale("Inlet", unclassed, "°C", relative)[1] is relative
    cmap, norm = cell_scale("Fans", unclassed, "%", relative)
    assert (norm.vmin, norm.vmax) == (0, 100)
    assert cmap.name == "RdYlGn_r"
    assert cell_scale("Fans", unclassed, "RPM", relative)[1] is relative
    # The power, not a temperature, from green to red on the relative scale of its column
    cmap, norm = cell_scale("Power", unclassed, "W", relative)
    assert (cmap.name, norm) == ("RdYlGn_r", relative)
    # The components green up to 30 °C, then up to red at 100 °C
    cmap, norm = cell_scale("Memory", unclassed, "°C", relative)
    assert (cmap.name, norm.vmin, norm.vmax) == ("RdYlGn_r", 30, 100)
    # The air of a server without class, on the relative scale of its column
    assert cell_scale("Inlet", unclassed, "°C", relative)[0].name == "RdYlBu_r"
    assert air_classes_line([classed, RackServer("c", 3, {}, ashrae={"air": "H1"}), unclassed]) == (
        "A1: 18–27 [15–32], H1: 18–22 [15–25]"
    )
    assert air_classes_line([classed], exhaust=True) == "A1: 15–32, 60 red"
    assert air_classes_line([unclassed]) is None


def test_exhaust_scale():
    """The exhaust of a server of an air class: green on its allowable range, then to red at 60 °C."""
    cmap, norm = cell_scale("Exhaust", RackServer("a", 1, {}, ashrae={"air": "A1"}), "°C", None)
    green = to_rgba(AIR_GREEN)
    assert all(np.allclose(cmap(norm(value)), green) for value in (10, 15, 25, 32))
    assert not np.allclose(cmap(norm(45)), green)
    assert np.allclose(cmap(norm(60)), cmap(norm(70)))
    assert cell_scale("Exhaust", RackServer("b", 2, {}), "°C", None)[1] is None


def test_inlet_scale():
    """The inlet of a server of an air class: green on its recommended range, dark out of its allowable one."""
    cmap, norm = cell_scale("Inlet", RackServer("a", 1, {}, ashrae={"air": "A1"}), "°C", None)
    green = to_rgba(AIR_GREEN)
    assert all(np.allclose(cmap(norm(value)), green) for value in (18, 22.5, 27))
    assert not np.allclose(cmap(norm(16)), green)
    assert not np.allclose(cmap(norm(30)), green)
    assert np.allclose(cmap(norm(14)), to_rgba(AIR_DARK_BLUE))
    assert np.allclose(cmap(norm(33)), to_rgba(AIR_DARK_RED))


@pytest.mark.parametrize(
    ("values", "classes", "style"),
    [
        ([27.0, 27.9], {"secondary": "S30"}, ("Secondary supply S30", SUPPLY_COLORS["below"])),
        ([27.0, 28.5], {"secondary": "S30"}, ("Secondary supply S30", SUPPLY_COLORS["close"])),
        ([29.0, 30.5], {"secondary": "S30"}, ("Secondary supply S30", SUPPLY_COLORS["above"])),
        ([27.0], {}, ("Secondary supply", "aliceblue")),
    ],
)
def test_circuit_style(values, classes, style):
    """A supply limited by an ASHRAE class, by its hottest window: green, orange within 2 °C of its maximum, red above."""
    assert circuit_style(CduCircuit("Secondary supply", values, False, "secondary"), classes) == style


def test_circuit_style_without_maximum():
    """W+ has no maximum, a return and a delta no class: their usual colors."""
    assert circuit_style(CduCircuit("Primary supply", [50.0], False, "primary"), {"primary": "W+"}) == (
        "Primary supply",
        "aliceblue",
    )
    assert circuit_style(CduCircuit("Primary ΔT", [6.0], True), {"primary": "W32"}) == ("Primary ΔT", "lavender")


def test_fans_of_several_units(tmp_path):
    """A rack mixing BMCs has fans in percent and in RPM: each server keeps its unit, colored on its scale."""
    traces = []
    for name, unit in (("hpe", "Percent"), ("dell", "RPM")):
        result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
        for fan in result["bench"]["cpu_17"]["monitoring"]["contexts"]["Fans"]["Fan"].values():
            fan["unit"] = unit
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), name, "BMC.Server"))
    rack = load_rack(SimpleNamespace(traces=traces), "cpu_17", {"hpe": 1, "dell": 2})
    assert rack.units["Fans"] == "%, RPM"
    assert {server.name: server.unit("Fans", rack.units) for server in rack.servers} == {"hpe": "%", "dell": "RPM"}
    assert "in %, from green at 0 % to red at 100 %; in RPM, from green, its slowest server" in colors_note(rack)


def test_rack_header(tmp_path):
    """The header gives the benchmark in bold and the workers of all the servers: the ones of the first server
    told 256 x stressng for servers of 64 to 640 cores."""
    traces = []
    for name, workers in (("small", 64), ("big", 640)):
        result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
        result["bench"]["cpu_17"]["workers"] = workers
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), name, "BMC.Server"))
    rack = load_rack(SimpleNamespace(traces=traces), "cpu_17", {"small": 1, "big": 2})
    header = graph_header(SimpleNamespace(title=""), "Rack elevation", "cpu_17", rack.bench, rack.workers)
    assert "Rack elevation during $\\bf{cpu\\_17}$ benchmark" in header
    assert "Stressor: [64;640] x $\\bf{stressng\\ cpu\\ int128}$ for 120 seconds" in header


def test_graph_racks(tmp_path):
    """A place holding several racks renders their elevation side by side; a single rack has its own."""
    result = json.loads(TRACES.joinpath("cdu_comparison.json").read_text())
    racks = []
    for rack in ("A12", "A13"):
        traces, positions = [], {}
        for position in (1, 3):
            name = f"{rack}-{position}"
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps(result))
            traces.append(Trace(str(path), name, "BMC.Server"))
            positions[name] = position
        racks.append((f"Rack {rack}", traces, positions))
    args = SimpleNamespace(
        width=1920, height=1080, title="", format="png", engine="cairo", dpi=72, verbose=False, events=[], traces=[]
    )
    assert graph_racks(args, "cpu_17", tmp_path, racks) == 1
    assert [path.name for path in tmp_path.glob("racks_*.png")] == ["racks_elevation_cpu_17.png"]
    assert graph_racks(args, "cpu_17", tmp_path, racks[:1]) == 0
