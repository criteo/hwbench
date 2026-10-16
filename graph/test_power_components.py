from graph.chassis import chassis_components
from graph.trace import Bench
from hwbench.bench.monitoring_structs import GPU_FAMILY, MonitoringContextKeys


def power(name: str, *values: float) -> dict:
    return {
        "name": name,
        "unit": "Watts",
        "mean": list(values),
        "min": list(values),
        "max": list(values),
        "stdev": [0.0] * len(values),
        "samples": [1] * len(values),
    }


class FakeTrace:
    """A trace of a server whose BMC meters its components, next to all-smi."""

    def get_trace(self) -> dict:
        bmc = ["Chassis", "Server", "Memory", "Fans", "Accelerators"]
        return {
            "bench": {
                "job_0": {
                    "monitoring": {
                        "metadata": {"samples_count": 2, "iteration_time": 10},
                        "contexts": {
                            "PowerConsumption": {
                                "BMC": {name: power(name, 100, 200) for name in bmc},
                                "GPU": {name: power(name, 300, 350) for name in ["GPU_0", "GPU_1"]},
                                "CPU": {"package": power("package", 150, 160)},
                            }
                        },
                    }
                }
            }
        }


def bench() -> Bench:
    bench = Bench(FakeTrace(), "job_0")
    bench.load_monitoring()
    return bench


def test_chassis_ignores_the_server_components():
    """The memory and accelerators power is neither a server nor shared on the chassis, unlike the fans."""
    assert chassis_components(bench()) == ["Chassis", "Server", "Fans"]


def test_gpu_graphs_ignore_the_accelerators_total():
    """The BMC total of the accelerators is not one more GPU of the per-GPU graphs."""
    gpus = bench().get_all_metrics(MonitoringContextKeys.PowerConsumption, GPU_FAMILY)
    assert sorted(gpu.get_name() for gpu in gpus) == ["GPU_0", "GPU_1"]
