from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from graph.hwgraph import graph_monitoring_metrics
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
