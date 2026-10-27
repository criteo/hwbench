from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import numpy as np
import pytest

from graph.rack import (
    RACK_METRICS,
    Rack,
    RackServer,
    Slot,
    exhaust,
    graph_rack,
    high_window,
    kept_windows,
    load_rack,
    low_window,
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


def windows(*means: list[float]):
    return [SimpleNamespace(get_mean=lambda values=values: values) for values in means]


def test_reduce_windows():
    """The sensors are reduced window by window, on the windows they all have."""
    assert reduce_windows(windows([1, 5, 3], [4, 2]), np.max) == [4, 5]
    assert reduce_windows(windows([1, 5], [3, 3]), np.mean) == [2, 4]
    assert reduce_windows(windows([], []), np.max) is None
    assert reduce_windows([], np.max) is None


class Monitoring:
    """A benchmark giving its thermal families, and the monitoring of its CDUs."""

    def __init__(self, thermal: dict | None = None, cdus: dict | None = None):
        self.thermal, self.cdus = thermal or {}, cdus

    def get_monitoring_metric(self, context):
        assert context == MonitoringContextKeys.Thermal
        return self.thermal

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
                ("Primary supply", [18.0, 18.5], False),
                ("Primary return", [24.0, 24.5], False),
                # On the windows having both
                ("Primary ΔT", [6.0], True),
                ("Secondary supply", [28.0, 28.0, 28.0], False),
                ("Secondary return", [34.0, 35.0, 36.0], False),
                ("Secondary ΔT", [6.0, 7.0, 8.0], True),
            ],
        )
    ]
    # Only the temperatures, and a return without its supply has no delta
    assert rack_cdus([Monitoring(cdus={"cdu-2": cdu({"primary_supply_temperature": [1.0]}, "Bar")})]) == []
    assert rack_cdus([Monitoring(cdus={"cdu-3": cdu({"primary_return_temperature": [24.0]})})]) == [
        ("cdu-3", [("Primary return", [24.0], False)])
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
        "Per window:\n    Inlet: the hottest Intake sensor;\n    CPUs: the mean of the CPU sensors;\n"
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
        return {index: sensor for index, sensor in enumerate(windows(*self.families[family]))}


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
    # The profiles of the rack, of its CPU and of its memory, without GPU, and the elevation with and without trends
    assert graph_rack(args, "cpu_17", tmp_path, positions) == 5
    assert sorted(path.name for path in tmp_path.glob("rack_*.png")) == [
        "rack_elevation_cpu_17.png",
        "rack_elevation_trends_cpu_17.png",
        "rack_profile_CPU_cpu_17.png",
        "rack_profile_Memory_cpu_17.png",
        "rack_profile_cpu_17.png",
    ]


def test_rack_power_of_the_traces(tmp_path):
    """The power of a server is the power metric given with its trace, not always the one of the BMC."""
    path = tmp_path / "server.json"
    path.write_text(TRACES.joinpath("cdu_comparison.json").read_text())
    trace = Trace(str(path), "server", "CPU.package")
    rack = load_rack(SimpleNamespace(traces=[trace]), "cpu_17", {"server": 1})
    package = trace.bench("cpu_17").get_monitoring_metric_by_name(MonitoringContextKeys.PowerConsumption, "CPU.package")
    assert rack.servers[0].series["Power"] == [float(value) for value in package.get_mean()]
    assert rack.power_metrics == ["CPU.package"]
