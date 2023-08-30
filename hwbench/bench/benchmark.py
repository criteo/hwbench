from typing import Any

from .parameters import BenchmarkParameters
from .engine import EngineModuleBase
from ..utils import helpers as h


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
