import os
import subprocess

from ..bench.benchmarks import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..utils.external import External


class EngineModuleQsort(EngineModuleBase):
    """This class implements the Qsort EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("qsort")

    def run(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run()


class EngineModuleCpu(EngineModuleBase):
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

    def run(self, p: BenchmarkParameters):
        return StressNGCPU(self, p).run()


class Engine(EngineBase):
    """The main stressn2 class."""

    def __init__(self):
        super().__init__("stressng", "stress-ng")
        self.add_module(EngineModuleCpu(self, "cpu"))
        self.add_module(EngineModuleQsort(self, "qsort"))

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[2]
        return self.version

    def version_major(self) -> int:
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class StressNG(External):
    """The StressNG CPU stressor."""

    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        External.__init__(self, parameters.out_dir)
        self.stressor_name = parameters.get_engine_module_parameter()
        self.engine_module = engine_module
        self.parameters = parameters

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        args = [
            self.engine_module.get_engine().get_binary(),
            "--timeout",
            str(self.parameters.get_runtime()),
            "--metrics-brief",
        ]
        if self.version_major() >= 16:
            args.insert(1, "--quiet")

        # Let's pin the CPU if needed
        if self.parameters.get_pinned_cpu():
            args.insert(0, f"{self.parameters.get_pinned_cpu()}")
            args.insert(0, "-c")
            args.insert(0, "taskset")
        return args

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name() + self.stressor_name

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)

    def version_major(self) -> int:
        return self.engine_module.get_engine().version_major()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        inp = stderr
        bogo_idx = 8
        line = -1
        if self.version_major() == 15:
            line = -2
        if self.version_major() >= 16:
            inp = stdout
            line = 2

        # TODO: better parsing than this
        score = float(inp.splitlines()[line].split()[bogo_idx])

        # Add the score to the global output
        return self.parameters.get_result_format() | {"bogo ops/s": score}

    def run(self):
        p = self.parameters
        print(
            "[{}] {}/{}/{}: {:3d} stressor on CPU {:3d} for {}s".format(
                p.get_name(),
                self.engine_module.get_engine().get_name(),
                self.engine_module.get_name(),
                p.get_engine_module_parameter(),
                p.get_engine_instances_count(),
                p.get_pinned_cpu(),
                p.get_runtime(),
            )
        )
        return super().run()


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


class StressNGQsort(StressNG):
    """The StressNG Qsort CPU stressor."""

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        return super().run_cmd() + [
            "--qsort",
            str(self.parameters.get_engine_instances_count()),
        ]
