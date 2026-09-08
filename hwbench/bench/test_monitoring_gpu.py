from unittest.mock import patch

from hwbench.bench.monitoring_structs import MonitoringContextKeys

from . import test_benchmarks_common as tbc

FAKE_GPUS = tbc.fake_gpus(2)


class TestMonitoringGPU(tbc.TestCommon):
    """The GPU part of the monitoring, on a mocked 2 GPUs server."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="hwbench/tests/parsing/cpu_info/v2321",
            numa="hwbench/tests/parsing/numa/8domainsllc",
        )

    def parse_with_gpus(self, gpus):
        """parse_jobs_config() on a host reporting <gpus>."""
        self.load_benches("./hwbench/config/monitoring.conf")
        self.parse_jobs_config(gpus=gpus)
        return self.benches.get_monitoring()

    def test_gpu_metrics_are_registered(self):
        monitoring = self.parse_with_gpus(FAKE_GPUS)
        assert monitoring.all_smi
        contexts = monitoring.metrics.contexts

        # 64 cores + 2 GPUs
        assert self.monitoring_members(monitoring, MonitoringContextKeys.Freq) == 66
        # cores + package + BMC + 2 GPUs
        assert self.monitoring_members(monitoring, MonitoringContextKeys.PowerConsumption) == 68
        assert self.monitoring_members(monitoring, MonitoringContextKeys.Utilization) == 2
        assert self.monitoring_members(monitoring, MonitoringContextKeys.Memory) == 2

        for index in range(2):
            name = f"GPU_{index}"
            assert name in contexts.PowerConsumption.GPU
            assert name in contexts.Freq.GPU
            assert name in contexts.Utilization.GPU
            assert name in contexts.Memory.GPU
            assert name in contexts.Thermal["GPU"]

    def test_gpu_metrics_survive_a_reset(self):
        """preup() resets the metrics, the GPU structures must be rebuilt."""
        monitoring = self.parse_with_gpus(FAKE_GPUS)
        # preup() also starts the all-smi exporter, which needs the binary.
        with (
            patch("hwbench.environment.all_smi.AllSMIMonitoring.start"),
            patch("hwbench.environment.all_smi.AllSMIMonitoring.stop"),
        ):
            monitoring.preup(precision_s=2)
            assert "GPU_0" in monitoring.metrics.contexts.PowerConsumption.GPU
            # The sampler must point at the new contexts, not the discarded ones.
            assert monitoring.all_smi.monitoring_contexts is monitoring.metrics.contexts
            monitoring.predown()

    def test_no_gpu(self):
        """A server without GPU registers no GPU metric and no sampler."""
        monitoring = self.parse_with_gpus({})
        assert monitoring.all_smi is None
        assert self.monitoring_members(monitoring, MonitoringContextKeys.Utilization) == 0
        assert self.monitoring_members(monitoring, MonitoringContextKeys.Freq) == 64
