import time
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
            "engine_module_parameter_base": self.parameters.get_engine_module_parameter_base(),
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
            h.fatal(f"Unsupported parameter for {e.get_engine().get_name()}/" f"{e.get_name()}: {error}")

    def run(self):
        e = self.get_enginemodule()
        p = self.get_parameters()
        # Extract the common result output
        p.set_result_format(self.format_results())
        # Exectue the engine module
        return e.run(p)

    def need_monitoring(self):
        """Return True if this benchmark requires monitoring."""
        return self.get_parameters().get_monitoring_config() != "none"


class ExternalBench(External):
    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        super().__init__(parameters.out_dir)
        self.monitoring = False
        if parameters.get_monitoring_config() == "all":
            self.monitoring = True
        self.runtime = parameters.get_runtime()
        self.parameters = parameters
        self.engine_module = engine_module
        self.skip = False

    def get_taskset(self, args):
        # Let's pin the CPU if needed
        if self.parameters.get_pinned_cpu():
            if isinstance(self.parameters.get_pinned_cpu(), list):
                cpu_list = ",".join([str(cpu) for cpu in self.parameters.get_pinned_cpu()])
                args.insert(0, f"{cpu_list}")
            else:
                args.insert(0, f"{self.parameters.get_pinned_cpu()}")
            args.insert(0, "-c")
            args.insert(0, "taskset")
        return args

    def fully_skipped_job(self) -> bool:
        """A method to know if the job should be fully skipped."""
        if not self.skip:
            return False

        if self.parameters.get_skip_method() == "wait":
            # The job is skipped but we were asked to make a no-op run
            return False

        return True

    def pre_run(self):
        status = ""
        if self.skip:
            status = " : skipped"
            if not self.fully_skipped_job():
                status += " with wait method"
        if self.monitoring and not self.fully_skipped_job():
            # Start the monitoring in background
            # It runs the same amount of time as the benchmark
            self.parameters.get_monitoring().monitor(2, 5, self.parameters.get_runtime())
        p = self.parameters
        cpu_location = ""
        if p.get_pinned_cpu():
            if isinstance(p.get_pinned_cpu(), (int, str)):
                cpu_location = " on CPU {:3d}".format(p.get_pinned_cpu())
            elif isinstance(p.get_pinned_cpu(), list):
                cpu_location = " on CPU [{}]".format(h.cpu_list_to_range(p.get_pinned_cpu()))
            else:
                h.fatal("Unsupported get_pinned_cpu() format :{}".format(type(p.get_pinned_cpu())))

        monitoring = ""
        if self.parameters.get_monitoring():
            monitoring = "(M)"
        print(
            "[{}] {}/{}/{}{}: {:3d} stressor{} for {}s{}".format(
                p.get_name(),
                self.engine_module.get_engine().get_name(),
                self.engine_module.get_name(),
                p.get_engine_module_parameter(),
                monitoring,
                p.get_engine_instances_count(),
                cpu_location,
                p.get_runtime(),
                status,
            )
        )

    def post_run(self, run):
        if self.monitoring and not self.fully_skipped_job():
            run["monitoring"] = self.parameters.get_monitoring().get_monitor_metrics()
        return run

    def empty_result(self):
        """A method to report empty results"""
        raise NotImplementedError

    def run(self):
        # Prepre the run
        self.pre_run()

        if not self.skip:
            # Run the benchmark
            run = super().run()
        else:
            # We'll return empty results, benchmark is not even called
            run = self.parameters.get_result_format() | self.empty_result()

            # But if we were asked to wait, let's sleep the same amount of time
            # as the original benchmark
            if not self.fully_skipped_job():
                time.sleep(self.parameters.get_runtime())

        # Clean the run
        return self.post_run(run)
