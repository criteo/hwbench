import os
import subprocess

from hwbench.bench.parameters import BenchmarkParameters

from .stressng import EngineBase, EngineModulePinnable, StressNG


class StressNGCPU(StressNG):
    """The StressNG CPU stressor."""

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        return super().run_cmd() + [
            "--cpu",
            str(self.parameters.get_engine_instances_count()),
            "--cpu-method",
            self.parameters.get_engine_module_parameter(),
        ]


class EngineModuleCpu(EngineModulePinnable):
    """This class implements the EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter()

    def list_module_parameters(self):
        english_env = os.environ.copy()
        english_env["LC_ALL"] = "C"
        cmd_out = subprocess.run(
            [self.engine.get_binary(), "--cpu-method", "list"],
            capture_output=True,
            env=english_env,
            stdin=subprocess.DEVNULL,
        )
        return (cmd_out.stdout or cmd_out.stderr).split(b":", 1)

    def load_module_parameter(self):
        out = self.list_module_parameters()
        methods = out[1].decode("utf-8").split()
        methods.remove("all")
        for method in methods:
            self.add_module_parameter(method)

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGCPU(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGCPU(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return StressNGCPU(self, p).fully_skipped_job()
