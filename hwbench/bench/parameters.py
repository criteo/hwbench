import pathlib

from hwbench.environment.hardware import BaseHardware

from .monitoring import Monitoring


class BenchmarkParameters:
    """A class to host parameters attached to a benchmark."""

    def __init__(
        self,
        out_dir: pathlib.Path,
        job_name: str,
        engine_instances: int,
        pinned_cpu,
        runtime: int,
        engine_module_parameter: str,
        engine_module_parameter_base: str,
        hw: BaseHardware,
        monitoring_config: str,
        monitoring: Monitoring,
        skip_method: str,
        sync_start: str,
    ):
        self.out_dir = out_dir
        self.job_name = job_name
        self.pinned_cpu = pinned_cpu
        self.engine_instances = engine_instances
        self.engine_module_parameter = engine_module_parameter
        self.engine_module_parameter_base = engine_module_parameter_base
        self.runtime = runtime
        self.result_format: dict[str, str] = {}
        self.hw = hw
        self.monitoring_config = monitoring_config
        self.monitoring = monitoring
        self.skip_method = skip_method
        self.sync_start = sync_start

    def get_benchmark(self):
        return self.benchmark

    def set_benchmark(self, benchmark):
        self.benchmark = benchmark

    def get_pinned_cpu(self):
        if self.pinned_cpu == "none":
            return ""
        return self.pinned_cpu

    def get_name(self) -> str:
        return self.job_name

    def get_name_with_position(self) -> str:
        if not self.benchmark:
            return self.get_name()
        return f"{self.get_name()}_{self.benchmark.get_job_number()}"

    def get_engine_instances_count(self) -> int:
        return self.engine_instances

    def get_engine_module_parameter(self) -> str:
        return self.engine_module_parameter

    def get_engine_module_parameter_base(self) -> str:
        return self.engine_module_parameter_base

    def get_runtime(self) -> int:
        return self.runtime

    def get_monitoring_config(self) -> str:
        return self.monitoring_config

    def get_monitoring(self) -> Monitoring:
        return self.monitoring

    def get_skip_method(self) -> str:
        return self.skip_method

    def get_sync_start(self) -> str:
        return self.sync_start

    def set_result_format(self, format):
        """Set the default result content to be padded with performance results."""
        self.result_format = format

    def get_result_format(self) -> dict[str, str]:
        """Get the default result content to be padded with performance results."""
        return self.result_format

    def get_hw(self) -> BaseHardware:
        return self.hw
