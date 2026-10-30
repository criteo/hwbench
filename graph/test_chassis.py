from __future__ import annotations

import copy
import json
import pathlib
from types import SimpleNamespace

import numpy as np

from graph.chassis import graph_chassis
from graph.graph import WARM_UP_ALPHA, Graph, yerr_graph
from graph.trace import Trace
from graph.windows import warm_up, without_warm_up
from hwbench.bench.monitoring_structs import MonitoringContextKeys

TRACES = pathlib.Path("documentation/example/traces")


def test_chassis_power_supplies(tmp_path, monkeypatch):
    """The power of the PSUs has a value per window, whatever the number of components of the chassis."""
    result = json.loads(TRACES.joinpath("cdu_reboot.json").read_text())
    bench_name = next(iter(result["bench"]))
    power = result["bench"][bench_name]["monitoring"]["PowerConsumption"]["BMC"]
    # A second component of the chassis, after the Server one of the trace
    power["Chassis"] = copy.deepcopy(power["Server"]) | {"name": "Chassis"}
    traces = []
    for index in range(2):
        path = tmp_path.joinpath(f"node-{index}.json")
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), f"node-{index}", "BMC.Server"))
    psus = traces[0].bench(bench_name).get_psu_power()

    curves = {}
    faded = []

    def record(graph, extra_legend=None):
        lines = graph.get_ax().get_lines()
        curves.update({line.get_label(): line.get_ydata() for line in lines if not line.get_label().startswith("_")})
        faded.extend(line for line in lines if line.get_alpha() == WARM_UP_ALPHA)

    monkeypatch.setattr(Graph, "render", record)
    args = SimpleNamespace(
        width=1920, height=1080, title="", format="png", engine="cairo", dpi=100, verbose=False, traces=traces
    )
    graph_chassis(args, bench_name, tmp_path)
    [psu_curve] = [values for label, values in curves.items() if label.startswith(MonitoringContextKeys.PowerSupplies)]
    # Without its warm up, above the whole curve faded: the dip and the peak of the reboot stay drawn
    np.testing.assert_allclose(psu_curve, without_warm_up(psus))
    assert np.isnan(psu_curve).sum() == 1
    assert any(np.allclose(line.get_ydata(), psus) for line in faded)


def test_yerr_graph_fades_the_warm_up(tmp_path, monkeypatch):
    """The errors of the warm up of a fan are drawn faded, with its curve, below the other windows."""
    trace = Trace(str(TRACES.joinpath("cdu_reboot.json")), "cdu_reboot", "BMC.Server")
    bench_name = next(iter(trace.get_trace()["bench"]))
    bench = trace.bench(bench_name)
    fan = next(iter(bench.get_component(MonitoringContextKeys.Fans, "Fan").values()))
    # A warm up window whose readings vary, for its error to be drawn
    fan.get_min()[0], fan.get_max()[0] = 10, 16
    drawn = {}

    def record(graph, extra_legend=None):
        drawn["containers"] = graph.get_ax().containers

    monkeypatch.setattr(Graph, "render", record)
    args = SimpleNamespace(width=1920, height=1080, title="", format="png", engine="cairo", dpi=100, verbose=False)
    yerr_graph(args, tmp_path, bench, MonitoringContextKeys.Fans, fan)
    faded, errors = drawn["containers"]
    [faded_bars] = faded.lines[2]
    assert faded_bars.get_alpha() == WARM_UP_ALPHA
    assert len(faded_bars.get_segments()) == np.count_nonzero(warm_up(fan.get_mean())) == 1
    assert np.isnan(errors.lines[0].get_ydata()[0])
