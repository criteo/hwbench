import re
from typing import Optional

from ..bench.parameters import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..bench.benchmark import ExternalBench
from ..utils import helpers as h


class EngineModulePinnable(EngineModuleBase):
    def validate_module_parameters(self, params: BenchmarkParameters):
        pinned = params.get_pinned_cpu()
        if pinned == "":
            return ""
        if not isinstance(pinned, list):
            pinned = [pinned]
        for cpu in pinned:
            if params.get_hw().logical_core_count() <= int(cpu):
                return f"Cannot pin on core #{cpu} we only have " f"{params.get_hw().logical_core_count()} cores"
        return ""


class Engine(EngineBase):
    """The main stressn2 class."""

    def __init__(self):
        from .stressng_cpu import EngineModuleCpu
        from .stressng_qsort import EngineModuleQsort
        from .stressng_memrate import EngineModuleMemrate
        from .stressng_stream import EngineModuleStream
        from .stressng_vnni import EngineModuleVNNI

        super().__init__("stressng", "stress-ng")
        self.add_module(EngineModuleCpu(self, "cpu"))
        self.add_module(EngineModuleQsort(self, "qsort"))
        self.add_module(EngineModuleStream(self, "stream"))
        self.add_module(EngineModuleMemrate(self, "memrate"))
        self.add_module(EngineModuleVNNI(self, "vnni"))
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

    def version_minor(self) -> int:
        if self.version:
            return int(self.version.split(b".")[2])
        return 0

    def get_version(self) -> Optional[str]:
        if self.version:
            return self.version.decode("utf-8")
        return None

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class StressNG(ExternalBench):
    """The StressNG base class for stressors."""

    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        ExternalBench.__init__(self, engine_module, parameters)
        self.stressor_name = parameters.get_engine_module_parameter()
        self.engine_module = engine_module
        self.parameters = parameters

    def version_compatible(self) -> bool:
        engine = self.engine_module.get_engine()
        return engine.version_major() >= 17 and engine.version_minor() >= 4

    def need_skip_because_version(self):
        if self.skip:
            # we already skipped this benchmark, we can't know the reason anymore
            # because we might not have run the version command.
            return ["echo", "skipped benchmark"]
        if not self.version_compatible():
            print(f"WARNING: skipping benchmark {self.name}, needs stress-ng >= 0.17.04")
            self.skip = True
            return ["echo", "skipped benchmark"]
        return None

    def run_cmd(self) -> list[str]:
        skip = self.need_skip_because_version()
        if skip:
            return skip

        # Let's build the command line to run the tool
        args = [
            self.engine_module.get_engine().get_binary(),
            "--timeout",
            str(self.parameters.get_runtime()),
            "--metrics",
        ]

        return self.get_taskset(args)

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name() + self.stressor_name

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)

    def version_major(self) -> int:
        return self.engine_module.get_engine().version_major()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def stats_parse(self) -> re.Pattern:
        """Return a regexp pattern to match the stats metrics"""
        # stress-ng: metrc: [58878] stressor       bogo ops real time  usr time  sys time   bogo ops/s     bogo ops/s CPU used per       RSS Max
        # stress-ng: metrc: [58878]                           (secs)    (secs)    (secs)   (real time) (usr+sys time) instance (%)          (KB)
        # stress-ng: metrc: [58878] stream            39999     10.01   1231.71     48.89      3995.57          31.23        99.94         14360

        return re.compile(
            r"stress-ng: metrc:"
            r"\s+\[(?P<pid>[0-9]+)\] "
            r"(?P<engine>[a-z]+) "
            r"\s+(?P<bogo_ops>[0-9]+) "
            r"\s+(?P<real_time>[0-9\.]+) "
            r"\s+(?P<user_time>[0-9\.]+) "
            r"\s+(?P<sys_time>[0-9\.]+) "
            r"\s+(?P<bogo_ops_sec>[0-9\.]+) "
            r"\s+(?P<bogo_ops_sec_realtime>[0-9\.]+)"
            r"\s+(?P<cpu_used_percent>[0-9\.]+)"
            r"\s+(?P<rss_max>[0-9\.]+)"
        )

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        """Generic stress-ng output parsing to extract performance metrics."""
        for line in (stdout or stderr).splitlines():
            stats = self.stats_parse().search(str(line))
            if stats:
                s = stats.groupdict()
                return self.parameters.get_result_format() | {
                    "bogo ops/s": float(s["bogo_ops_sec"]),
                    "effective_runtime": float(s["real_time"]),
                }

        h.fatal("Unable to detect stress-ng reporting metrics")

    def empty_result(self):
        """Default empty results for stress-ng"""
        return {
            "bogo ops/s": 0,
            "effective_runtime": 0,
            "skipped": True,
        }
