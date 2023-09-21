import json
import subprocess
from typing import Any

from .parameters import BenchmarkParameters
from .engine import EngineModuleBase
from ..utils import helpers as h
from ..utils.external import External


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
            "job_number": self.get_job_number(),
            "job_name": self.parameters.get_name(),
        }

    def validate_parameters(self):
        """Verify that the benchmark parameters are correct at instanciation time.
        Returns empty string if OK, or an error message"""
        e = self.get_enginemodule()
        p = self.get_parameters()
        error = e.validate_module_parameters(p)
        if error:
            h.fatal(
                f"Unsupported parameter for {e.get_engine().get_name()}/"
                f"{e.get_name()}: {error}"
            )

    def run(self):
        e = self.get_enginemodule()
        p = self.get_parameters()
        # Extract the common result output
        p.set_result_format(self.format_results())
        # Exectue the engine module
        return e.run(p)


class ExternalBench(External):
    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        super().__init__(parameters.out_dir)
        self.monitoring = False
        if parameters.get_monitoring() == "all":
            self.monitoring = True
        self.runtime = parameters.get_runtime()
        self.parameters = parameters
        self.engine_module = engine_module

    def get_taskset(self, args):
        # Let's pin the CPU if needed
        if self.parameters.get_pinned_cpu():
            if isinstance(self.parameters.get_pinned_cpu(), list):
                cpu_list = ",".join(
                    [str(cpu) for cpu in self.parameters.get_pinned_cpu()]
                )
                args.insert(0, f"{cpu_list}")
            else:
                args.insert(0, f"{self.parameters.get_pinned_cpu()}")
            args.insert(0, "-c")
            args.insert(0, "taskset")
        return args

    def run(self):
        if self.monitoring:
            # Start the monitoring in background
            # It runs the same amount of time as the benchmark
            report_power = subprocess.Popen(
                [
                    "python3",
                    "-m",
                    "report_power.report_power",
                    "--name",
                    "monitoring",
                    "--simple",
                    "--limit",
                    f"{self.parameters.get_runtime()}",
                    "--interval",
                    "10",
                ],
                cwd="/root",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        p = self.parameters
        cpu_location = ""
        if p.get_pinned_cpu():
            if isinstance(p.get_pinned_cpu(), (int, str)):
                cpu_location = " on CPU {:3d}".format(p.get_pinned_cpu())
            elif isinstance(p.get_pinned_cpu(), list):
                cpu_location = " on CPU {}".format(str(p.get_pinned_cpu()))
            else:
                h.fatal(
                    "Unsupported get_pinned_cpu() format :{}".format(
                        type(p.get_pinned_cpu())
                    )
                )

        monitoring = ""
        if self.parameters.get_monitoring():
            monitoring = "(M)"
        print(
            "[{}] {}/{}/{}{}: {:3d} stressor{} for {}s".format(
                p.get_name(),
                self.engine_module.get_engine().get_name(),
                self.engine_module.get_name(),
                p.get_engine_module_parameter(),
                monitoring,
                p.get_engine_instances_count(),
                cpu_location,
                p.get_runtime(),
            )
        )

        # Run the benchmark
        run = super().run()

        if self.monitoring:
            # Collect output and extract metrics
            (
                stdout,
                stderr,
            ) = report_power.communicate()  # pyright: ignore [reportUnboundVariable]
            if stderr:
                h.fatal(f"External_Bench: report_power failed : {stderr}")
            try:
                run["monitoring"] = json.loads(stdout.decode())["monitoring"]["metrics"]
            except json.JSONDecodeError:
                h.fatal(
                    f"External_Bench: invalid report_power output : {stdout.decode()}"
                )

        return run
