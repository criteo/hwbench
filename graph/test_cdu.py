from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from graph.cdu import WINDOW_MEAN_LEGEND, cdu_series, graph_cdu


def cdu_data():
    return {
        "metrics": {"temperature": {"name": "Supply temperature", "unit": "Celsius"}},
        "readings": {"temperature": {"mean": [20, None, 0], "samples": [1, 0, 5]}},
    }


def test_failed_polls_leave_gaps_and_valid_zero_survives():
    name, timestamps, values = cdu_series(cdu_data(), 10)["Celsius"][0]
    assert name == "Supply temperature"
    assert timestamps == [0, 10, 20]
    assert values[0] == 20
    assert np.isnan(values[1])
    assert values[2] == 0


def test_cdu_graph_uses_shared_host_aggregation_grid(monkeypatch, tmp_path):
    graph = MagicMock()
    factory = MagicMock(return_value=graph)
    monkeypatch.setattr("graph.cdu.Graph", factory)
    bench = SimpleNamespace(
        get=lambda key: {"metadata": {"samples_count": 3, "iteration_time": 10}, "cdus": {"../cooling": cdu_data()}},
        get_bench_name=lambda: "job",
        get_system_title=lambda: "server",
        duration=lambda: 30,
    )
    trace = SimpleNamespace(bench=lambda name: bench, get_name=lambda: "server")
    args = SimpleNamespace(title="", traces=[])
    monkeypatch.setattr("graph.cdu.context_header", lambda args: "")
    assert graph_cdu(args, trace, "job", tmp_path) == 1
    plot = graph.get_ax.return_value.plot.call_args
    assert plot.args[0] == [0, 10, 20]
    assert np.isnan(plot.args[1][1])
    assert factory.call_args.args[4].is_relative_to(tmp_path / "server" / "job" / "CDU")
    graph.render.assert_called_once()
    assert factory.call_args.kwargs["legend_title"] == WINDOW_MEAN_LEGEND
    # Window means 20 and 0 contribute equally, independent of per-window sample counts.
    assert plot.kwargs["label"] == "Supply temperature [0.0; 10.0; 10.0; 20.0]"


def test_runs_without_cdus_have_no_cdu_graphs(tmp_path):
    trace = SimpleNamespace(bench=lambda name: SimpleNamespace(get=lambda key: {}))
    assert graph_cdu(None, trace, "job", tmp_path) == 0


def test_graphs_use_metric_units_without_assuming_hpe_sensor_types(monkeypatch, tmp_path):
    data = {
        "metrics": {
            "bypass_duty": {"name": "Bypass duty cycle", "unit": "Percent"},
            "alarm_code": {"name": "Alarm code", "unit": "raw"},
            "conductivity": {"name": "Coolant conductivity", "unit": "uS/cm"},
        },
        "readings": {
            key: {"mean": [value]} for key, value in {"bypass_duty": 20, "alarm_code": 0, "conductivity": 23.5}.items()
        },
    }
    factory = MagicMock()
    monkeypatch.setattr("graph.cdu.Graph", factory)
    bench = SimpleNamespace(
        get=lambda key: {"metadata": {"samples_count": 1, "iteration_time": 10}, "cdus": {"other-vendor": data}},
        get_bench_name=lambda: "job",
        get_system_title=lambda: "server",
        duration=lambda: 5,
    )
    trace = SimpleNamespace(bench=lambda name: bench, get_name=lambda: "server")
    args = SimpleNamespace(title="")
    assert graph_cdu(args, trace, "job", tmp_path) == 3
    assert [call.args[5] for call in factory.call_args_list] == [
        "Percentage readings",
        "Raw readings",
        "uS%2Fcm",
    ]


def comparison_data():
    from graph.cdu import CIRCUIT_TEMPERATURES

    data = {
        "metrics": {key: {"name": key.replace("_", " "), "unit": "Celsius"} for key in CIRCUIT_TEMPERATURES},
        "readings": {key: {"mean": [20, None, 0]} for key in CIRCUIT_TEMPERATURES},
    }
    data["metrics"]["ambient_temperature"] = {"name": "Ambient", "unit": "Celsius"}
    data["readings"]["ambient_temperature"] = {"mean": [25, 25, 25]}
    monitoring = {
        "metadata": {"samples_count": 3, "iteration_time": 10},
        "contexts": {
            "Thermal": {"CPU": {"socket1": {"name": "Socket 1", "unit": "Celsius", "mean": [50, 55, 52]}}},
            "PowerConsumption": {
                "CPU": {
                    "package": {"unit": "Watts", "mean": [100, 110, 120]},
                    "Core_0": {"unit": "Watts", "mean": [1, 2, 3]},
                },
                "BMC": {"Server": {"unit": "Watts", "mean": [200, 210, 220]}},
            },
        },
        "cdus": {"other-vendor": data},
    }
    return monitoring, data


def test_comparison_selects_circuits_cpu_and_selected_power_preserving_gaps():
    from graph.cdu import cdu_host_series

    monitoring, data = comparison_data()
    temperatures, watts = cdu_host_series(monitoring, data, "BMC.Server")
    assert len(temperatures) == 5  # Four circuits and one CPU; no ambient reading.
    assert [label for label, _ in watts] == ["CPU.package", "BMC.Server"]
    assert np.isnan(temperatures[0][1][1])
    assert temperatures[0][1][2] == 0
    # Short host series retain a trailing gap rather than a fabricated value.
    monitoring["contexts"]["Thermal"]["CPU"]["socket1"]["mean"] = [50, 55]
    temperatures, watts = cdu_host_series(monitoring, data, "CPU.package")
    assert np.isnan(temperatures[-1][1][-1])
    assert [label for label, _ in watts] == ["CPU.package"]


def test_comparison_is_automatic_with_separate_temperature_and_power_axes(monkeypatch, tmp_path):
    from graph.cdu import HOST_COMPARISON

    monitoring, data = comparison_data()
    factory = MagicMock()
    monkeypatch.setattr("graph.cdu.Graph", factory)
    monkeypatch.setattr("graph.cdu.context_header", lambda args: "")
    bench = SimpleNamespace(
        get=lambda key: monitoring,
        get_bench_name=lambda: "job",
        get_system_title=lambda: "server",
        duration=lambda: 30,
    )
    trace = SimpleNamespace(bench=lambda name: bench, get_name=lambda: "server", metric_name="BMC.Server")
    assert graph_cdu(SimpleNamespace(title=""), trace, "job", tmp_path) == 2
    assert factory.call_args.args[3] == "Temperature (°C)"
    assert factory.call_args.args[5] == HOST_COMPARISON
    assert factory.call_args.kwargs["legend_title"] == WINDOW_MEAN_LEGEND
    graph = factory.return_value
    graph.set_y2_axis.assert_called_once_with("Power (Watts)")
    power_calls = graph.get_ax2.return_value.plot.call_args_list
    assert [call.kwargs["linestyle"] for call in power_calls] == ["--", "--"]
    assert power_calls[0].args[0] == [0, 10, 20]
    assert power_calls[0].args[1] == [100, 110, 120]
    # All CPU and CDU curves use the common grid on the first axis.
    cpu_call = graph.get_ax.return_value.plot.call_args
    assert cpu_call.args[0] == [0, 10, 20]
    assert cpu_call.args[1] == [50, 55, 52]


def test_comparison_skips_unavailable_sources(monkeypatch, tmp_path):
    from graph.cdu import graph_cdu_host

    monitoring, data = comparison_data()
    bench = SimpleNamespace(get=lambda key: monitoring)
    trace = SimpleNamespace(metric_name="BMC.Server")
    factory = MagicMock()
    monkeypatch.setattr("graph.cdu.Graph", factory)
    for source in ["Thermal", "PowerConsumption"]:
        removed = monitoring["contexts"].pop(source)
        assert graph_cdu_host(None, trace, bench, "cooling", data, tmp_path) == 0
        monitoring["contexts"][source] = removed
    factory.assert_not_called()
