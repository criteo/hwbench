from __future__ import annotations

import copy
import json
import pathlib
from types import SimpleNamespace

import numpy as np

from graph.chassis import graph_chassis
from graph.graph import Graph
from graph.trace import Trace
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

    def record(graph, extra_legend=None):
        curves.update({line.get_label(): line.get_ydata() for line in graph.get_ax().get_lines()})

    monkeypatch.setattr(Graph, "render", record)
    args = SimpleNamespace(
        width=1920, height=1080, title="", format="png", engine="cairo", dpi=100, verbose=False, traces=traces
    )
    graph_chassis(args, bench_name, tmp_path)
    [psu_curve] = [values for label, values in curves.items() if label.startswith(MonitoringContextKeys.PowerSupplies)]
    np.testing.assert_allclose(psu_curve, psus)
