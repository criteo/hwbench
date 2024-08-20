from ..bench.parameters import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..bench.benchmark import ExternalBench


class EngineModuleCmdline(EngineModuleBase):
    """This class implements the EngineModuleBase for fio"""

    def __init__(self, engine: EngineBase, engine_module_name: str, fake_stdout=None):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter(fake_stdout)

    def load_module_parameter(self, fake_stdout=None):
        # if needed add module parameters to your module
        self.add_module_parameter("cmdline")

    def validate_module_parameters(self, p: BenchmarkParameters):
        msg = super().validate_module_parameters(p)
        Fio(self, p).parse_parameters()
        return msg

    def run_cmd(self, p: BenchmarkParameters):
        return Fio(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return Fio(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return Fio(self, p).fully_skipped_job()


class Engine(EngineBase):
    """The main fio class."""

    def __init__(self, fake_stdout=None):
        super().__init__("fio", "fio")
        self.add_module(EngineModuleCmdline(self, "cmdline", fake_stdout))

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        print(stdout)
        self.version = stdout.split(b"-")[1]
        return self.version

    def version_major(self) -> int:
        if self.version:
            return int(self.version.split(b".")[0])
        return 0

    def version_minor(self) -> int:
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class Fio(ExternalBench):
    """The Fio stressor."""

    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        ExternalBench.__init__(self, engine_module, parameters)
        self.parameters = parameters
        self.engine_module = engine_module
        self.parse_parameters()

    def parse_parameters(self):
        runtime = self.parameters.runtime

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        args = [
            self.engine_module.get_engine().get_binary(),
            str(self.parameters.get_runtime()),
        ]

        return self.get_taskset(args)

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
