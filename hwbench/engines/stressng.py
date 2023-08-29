import os
import re
import subprocess

from typing import Optional, Any

from ..bench.benchmarks import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..utils.external import External
from ..utils import helpers as h


class EngineModuleQsort(EngineModuleBase):
    """This class implements the Qsort EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("qsort")

    def run(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run()


class EngineModuleStream(EngineModuleBase):
    """This class implements the Stream EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("stream")

    def run(self, p: BenchmarkParameters):
        return StressNGStream(self, p).run()

    def validate_module_parameters(self, params: BenchmarkParameters):
        if params.get_runtime() < 5:
            return "StressNGStream needs at least a 5s of run time"


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
        self.add_module(EngineModuleStream(self, "stream"))
        self.version = None

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

    def get_version(self) -> Optional[str]:
        if self.version:
            return self.version.decode("utf-8")
        return None

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
        score = 0
        try:
            score = float(inp.splitlines()[line].split()[bogo_idx])
        except IndexError:
            h.fatal(f"At line {line}, could not get element #{bogo_idx} of: '{inp}'")

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


class StressNGStream(StressNG):
    """The StressNG STREAM memory stressor."""

    def run_cmd(self) -> list[str]:
        # TODO: handle get_pinned_cpu ; it does not necessarily make sense for this
        # benchmark, but it could be revisited once we support pinning on multiple CPUs.
        if self.engine_module.get_engine().get_version() != "0.16.04":
            raise NotImplementedError(
                "StressNGStream needs stress-ng version 0.16.04 ; "
                "later version have different --metrics vs --metrics-brief options; "
                "earlier version format memory bandwidth differently"
            )
        ret: list[str] = [
            self.engine_module.get_engine().get_binary(),
            "--timeout",
            str(self.parameters.get_runtime()),
            "--metrics-brief",
            "--stream",
            str(self.parameters.get_engine_instances_count()),
        ]

        self.stream_l3_size: Optional[int] = None
        if self.stream_l3_size is not None:
            ret.extend(["--stream-l3-size", str(self.stream_l3_size)])

        return ret

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        detail_rate = re.compile(r"\] stream: memory rate: ")
        summary_rate = re.compile(r"\] stream ")
        detail_parse = re.compile(
            r"memory rate: (?P<read>[0-9\.]+) MB read/sec, "
            r"(?P<write>[0-9\.]+) MB write/sec, "
            r"(?P<flop>[0-9\.]+) double precision Mflop/sec "
            r"\(instance (?P<instance>[0-9]+)\)"
        )
        summary_parse = re.compile(
            r"stream\s+(?P<rate>[0-9\.]+) "
            r"(?:(?:MB per sec memory)|(?:Mflop per sec \(double precision\))) "
            r"(?P<source>read|write|compute) rate"
        )

        out = (stdout or stderr).splitlines()

        detail = [str(line) for line in out if detail_rate.search(str(line))]
        summary = [str(line) for line in out if summary_rate.search(str(line))]

        detail_size = self.parameters.get_engine_instances_count() or len(detail)

        ret = {
            "detail": {
                "read": [0] * detail_size,
                "write": [0] * detail_size,
                "Mflop/s": [0] * detail_size,
            },
            "read": 0,
            "write": 0,
            "Mflop/s": 0,
        }

        for line in detail:
            matches = detail_parse.search(line)
            if matches is not None:
                r = matches.groupdict()
                instance = int(r["instance"])
                ret["detail"]["read"][instance] = float(r["read"])
                ret["detail"]["write"][instance] = float(r["write"])
                ret["detail"]["Mflop/s"][instance] = float(r["flop"])

        for line in summary:
            matches = summary_parse.search(line)
            if matches is not None:
                r = matches.groupdict()
                source = r["source"]
                if source == "read" or source == "write":
                    ret[source] = float(r["rate"])
                elif source == "compute":
                    ret["Mflop/s"] = float(r["rate"])

        return ret | self.parameters.get_result_format()
