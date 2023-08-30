import pathlib
from typing import Any

from .engine import EngineModuleBase
from ..utils import helpers as h


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
    ):
        self.out_dir = out_dir
        self.job_name = job_name
        self.pinned_cpu = pinned_cpu
        self.engine_instances = engine_instances
        self.engine_module_parameter = engine_module_parameter
        self.runtime = runtime
        self.result_format = {}

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


class Benchmark:
    """Class to define a benchmark."""

    def __init__(
        self,
        job_number: int,
        enginemodule: EngineModuleBase,
        parameters: BenchmarkParameters,
    ):
        self.job_number = job_number
        self.enginemodule = enginemodule
        self.parameters = parameters
        invalid = self.validate_parameters()
        if invalid:
            h.fatal(
                f"Unsupported parameter for {enginemodule.get_engine().get_name()}/"
                f"{enginemodule.get_name()}: {invalid}"
            )

    def get_enginemodule(self) -> EngineModuleBase:
        return self.enginemodule

    def get_parameters(self) -> BenchmarkParameters:
        return self.parameters

    def get_job_number(self) -> int:
        return self.job_number

    def format_results(self) -> dict[str, Any]:
        """Format the default result content to be padded with performance results."""
        return {
            "engine": self.get_enginemodule().get_engine().get_name(),
            "engine_module": self.get_enginemodule().get_name(),
            "engine_module_parameter": self.parameters.get_engine_module_parameter(),
            "timeout": self.parameters.get_runtime(),
            "cpu_pin": self.parameters.get_pinned_cpu(),
            "workers": self.parameters.get_engine_instances_count(),
        }

    def validate_parameters(self) -> str:
        """Verify that the benchmark parameters are correct at instanciation time.
        Returns empty string if OK, or an error message"""
        e = self.get_enginemodule()
        p = self.get_parameters()
        return e.validate_module_parameters(p)

    def run(self):
        e = self.get_enginemodule()
        p = self.get_parameters()
        # Extract the common result output
        p.set_result_format(self.format_results())
        # Exectue the engine module
        return e.run(p)
