from ..bench.parameters import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..utils.external import External


class EngineModuleSleep(EngineModuleBase):
    """This class implements the EngineModuleBase for Sleep"""

    def __init__(self, engine: EngineBase, engine_module_name: str, fake_stdout=None):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter(fake_stdout)

    def load_module_parameter(self, fake_stdout=None):
        # if needed add module parameters to your module
        self.add_module_parameter("sleep")

    def run(self, p: BenchmarkParameters):
        print(
            "[{}] {}/{}/{}: {:3d} sleeper on CPU {:3d} for {}s".format(
                p.get_name(),
                self.get_engine().get_name(),
                self.get_name(),
                p.get_engine_module_parameter(),
                p.get_engine_instances_count(),
                p.get_pinned_cpu(),
                p.get_runtime(),
            )
        )
        return Sleep(self, p).run()


class Engine(EngineBase):
    """The main sleep class."""

    def __init__(self, fake_stdout=None):
        super().__init__("sleep", "sleep")
        self.add_module(EngineModuleSleep(self, "sleep", fake_stdout))

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    def version_major(self) -> int:
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class Sleep(External):
    """The Sleep stressor."""

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
            self.parameters.get_runtime(),
        ]

        # Let's pin the CPU if needed
        if self.parameters.get_pinned_cpu():
            args.insert(0, f"{self.parameters.get_pinned_cpu()}")
            args.insert(0, "-c")
            args.insert(0, "taskset")

        return args

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        # Add the score to the global output
        return self.parameters.get_result_format() | {
            "bogo ops/s": self.parameters.get_runtime()
        }

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)
