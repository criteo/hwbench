from types import SimpleNamespace

from graph.graph import redfish_timeouts, timeouts_graph
from graph.trace import Bench


def counts(name: str, unit: str, totals: list[int], samples: int = 5) -> dict:
    """A per-iteration count, aggregated over windows of <samples> iterations."""
    return {
        "name": name,
        "unit": unit,
        "mean": [total / samples for total in totals],
        "min": [0.0] * len(totals),
        "max": [float(total) for total in totals],
        "stdev": [0.0] * len(totals),
        "samples": [samples] * len(totals),
    }


class FakeTrace:
    def __init__(self, monitor: dict):
        self.monitor = monitor

    def get_trace(self) -> dict:
        return {
            "bench": {
                "job_0": {
                    "monitoring": {
                        "metadata": {"samples_count": 3, "iteration_time": 10},
                        "contexts": {"Monitor": self.monitor},
                    }
                }
            }
        }


def bench(monitor: dict) -> Bench:
    bench = Bench(FakeTrace(monitor), "job_0")
    bench.load_monitoring()
    return bench


def test_redfish_timeouts():
    """The timeouts of each window are the mean of the iterations times their number."""
    monitor = {
        "BMC": {
            "Polling": counts("Polling", "ms", [100, 100, 100]),
            "Timeouts": counts("Timeouts", "requests", [0, 3, 1]),
        },
        # Without any PDU, the metric has no sample
        "PDU": {"Timeouts": {"name": "Timeouts", "unit": "requests"}},
    }
    assert redfish_timeouts(bench(monitor)) == {"BMC": [0, 3, 1]}


def test_no_timeouts_graph_without_timeout():
    """A trace made before the timeouts were saved, or without any timeout, gets no timeouts graph."""
    args = SimpleNamespace(verbose=False)
    before = {"BMC": {"Polling": counts("Polling", "ms", [100, 100, 100])}}
    assert redfish_timeouts(bench(before)) == {}
    assert timeouts_graph(args, None, bench(before)) == 0
    none = {"BMC": {"Timeouts": counts("Timeouts", "requests", [0, 0, 0])}}
    assert timeouts_graph(args, None, bench(none)) == 0
