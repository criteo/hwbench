import pathlib

from ..environment.hardware import BaseHardware


class BenchmarkParameters:
    """A class to host parameters attached to a benchmark."""

    def __init__(
        self,
        out_dir: pathlib.Path,
        job_name: str,
        engine_instances: int,
        pinned_cpu: str,
        runtime: int,
        engine_module_parameter: str,
        hw: BaseHardware,
    ):
        self.out_dir = out_dir
        self.job_name = job_name
        self.pinned_cpu = pinned_cpu
        self.engine_instances = engine_instances
        self.engine_module_parameter = engine_module_parameter
        self.runtime = runtime
        self.result_format = {}
        self.hw = hw

    def get_pinned_cpu(self) -> str:
        return self.pinned_cpu

    def get_name(self) -> str:
        return self.job_name

    def get_engine_instances_count(self) -> int:
        return self.engine_instances

    def get_engine_module_parameter(self) -> str:
        return self.engine_module_parameter

    def get_runtime(self) -> int:
        return self.runtime

    def set_result_format(self, format):
        """Set the default result content to be padded with performance results."""
        self.result_format = format

    def get_result_format(self) -> dict[str, str]:
        """Get the default result content to be padded with performance results."""
        return self.result_format

    def get_hw(self) -> BaseHardware:
        return self.hw
