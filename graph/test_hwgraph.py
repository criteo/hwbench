from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from graph.hwgraph import graph_fans, graph_monitoring_metrics, main
from graph.trace import Trace
from hwbench.bench.monitoring_structs import MonitorContextKeys


def render_monitor(present: dict) -> list[str]:
    """Render the Monitor graphs of a bench holding only the keys of present, return the rendered metrics."""

    def get_component(_context, key):
        if key not in present:
            raise KeyError(key)
        return {key: present[key]}

    trace = MagicMock()
    trace.bench.return_value.get_component.side_effect = get_component
    with patch("graph.hwgraph.yerr_graph", return_value=1) as yerr:
        rendered = graph_monitoring_metrics(SimpleNamespace(verbose=False), trace, "job_0", "out")
    assert rendered == yerr.call_count
    return [call.args[4] for call in yerr.call_args_list]


def test_monitor_context_missing():
    """A trace without the Monitor context renders nothing instead of crashing."""
    assert render_monitor({}) == []


def test_monitor_key_missing():
    """A missing key is skipped, not rendered again with the metric of the previous key."""
    # BMC comes first: the missing PDU, CPU, GPU and CDU used to render it again
    bmc = MagicMock(**{"get_samples.return_value": [1.0]})
    assert render_monitor({MonitorContextKeys.BMC: bmc}) == [bmc]


def test_ashrae_option(capsys):
    """--ashrae takes known classes separated by commas, at most one per family."""
    with (
        patch(
            "sys.argv",
            [
                "hwgraph",
                "graph",
                "--traces",
                "documentation/example/traces/numa.json::BMC.Server",
                "--outdir",
                "out",
                "--ashrae",
                "A1,A2",
            ],
        ),
        pytest.raises(SystemExit),
    ):
        main()
    assert "--ashrae: 'A1', 'A2' are classes of the same family, one per family" in capsys.readouterr().err


def missing_trace(path, fans: int = 12) -> Trace:
    """A trace of the reference dataset, of 12 samples, whose PSUs miss the last 2 and its fans all but <fans>."""
    result = json.loads(pathlib.Path("documentation/example/traces/cdu_comparison.json").read_text())
    contexts = result["bench"]["cpu_17"]["monitoring"]["contexts"]
    for sensors, count in ((contexts["PowerSupplies"]["BMC"], 10), (contexts["Fans"]["Fan"], fans)):
        for sensor in sensors.values():
            for field in ("mean", "min", "max", "stdev", "samples"):
                sensor[field] = sensor[field][:count]
    path.write_text(json.dumps(result))
    return Trace(str(path), "server", "BMC.Server")


def missing_args(option: str) -> SimpleNamespace:
    return SimpleNamespace(
        width=1920,
        height=1080,
        title="",
        format="png",
        engine="cairo",
        dpi=72,
        verbose=False,
        events=[],
        ignore_missing_datapoint=option,
    )


@pytest.mark.parametrize("option", ["last", "zero"])
def test_missing_samples_of_a_host(tmp_path, option):
    """The graphs of a host replace the missing samples of its fans, and of its PSUs drawn with its power, as
    --ignore-missing-datapoint says."""
    assert graph_fans(missing_args(option), missing_trace(tmp_path / "server.json", fans=11), "cpu_17", tmp_path) > 0


def test_missing_samples_of_a_host_without_the_option(tmp_path, capsys):
    """Without --ignore-missing-datapoint, a missing sample of the PSUs stops the graphs of a host, as one of the
    other sensors does."""
    with pytest.raises(SystemExit):
        graph_fans(missing_args(""), missing_trace(tmp_path / "server.json"), "cpu_17", tmp_path)
    assert "server/cpu_17: PowerSupplies is missing the 11th data point" in capsys.readouterr().err


def test_no_environment_of_a_skipped_job(tmp_path):
    """A host renders the environment of the jobs it ran, not of a job it skipped, like an AVX-512 one on a CPU
    without it: it has no monitoring."""
    from graph.hwgraph import _collect_environment_tasks, _task_env_bench
    from graph.test_trace import avx_trace

    traces = [avx_trace(tmp_path / f"{name}.json", skipped=name == "skipped") for name in ("ran", "skipped")]
    args = SimpleNamespace(no_env=True, same_chassis=False, verbose=False, traces=traces)
    tasks = _collect_environment_tasks(args, tmp_path)
    env = [(traces[task[1]].get_name(), task[2]) for task in tasks if task[0] is _task_env_bench]
    assert sorted(env) == [("ran", "avx_0"), ("ran", "cpu_17"), ("skipped", "cpu_17")]
