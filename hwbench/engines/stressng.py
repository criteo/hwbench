import os
import re
import subprocess
from collections.abc import Iterable
from typing import NamedTuple, Callable

from typing import Optional, Any

from ..environment.hardware import BaseHardware
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
                return (
                    f"Cannot pin on core #{cpu} we only have "
                    f"{params.get_hw().logical_core_count()} cores"
                )


class EngineModuleQsort(EngineModulePinnable):
    """This class implements the Qsort EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("qsort")

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run()


class EngineModuleMemrate(EngineModulePinnable):
    """This class implements the Memrate EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("memrate")

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGMemrate(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGMemrate(self, p).run()


class EngineModuleStream(EngineModulePinnable):
    """This class implements the Stream EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("stream")

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGStream(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGStream(self, p).run()

    def validate_module_parameters(self, params: BenchmarkParameters):
        msg = super().validate_module_parameters(params)
        if params.get_runtime() < 5:
            return "{msg}; StressNGStream needs at least a 5s of run time"
        return msg


class EngineModuleVNNI(EngineModulePinnable):
    """This class implements the VNNI EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("vnni")
        self.methods = StressNGVNNIMethods()
        for method in self.methods.enumerate():
            self.add_module_parameter(method)

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run()


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


class Engine(EngineBase):
    """The main stressn2 class."""

    def __init__(self):
        super().__init__("stressng", "stress-ng")
        self.add_module(EngineModuleCpu(self, "cpu"))
        self.add_module(EngineModuleQsort(self, "qsort"))
        self.add_module(EngineModuleStream(self, "stream"))
        self.add_module(EngineModuleMemrate(self, "memrate"))
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

    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        ExternalBench.__init__(self, engine_module, parameters)
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
            "avg_read": 0,
            "avg_write": 0,
            "avg_Mflop/s": 0,
            "avg_total": 0,
            "sum_read": 0,
            "sum_write": 0,
            "sum_Mflop/s": 0,
            "sum_total": 0,
        }

        for line in detail:
            matches = detail_parse.search(line)
            if matches is not None:
                r = matches.groupdict()
                instance = int(r["instance"])
                ret["detail"]["read"][instance] = float(r["read"])
                ret["detail"]["write"][instance] = float(r["write"])
                ret["detail"]["Mflop/s"][instance] = float(r["flop"])
                ret["sum_read"] += float(r["read"])
                ret["sum_write"] += float(r["write"])
                ret["sum_Mflop/s"] += float(r["flop"])

        for line in summary:
            matches = summary_parse.search(line)
            if matches is not None:
                r = matches.groupdict()
                source = r["source"]
                if source == "read" or source == "write":
                    ret[f"avg_{source}"] = float(r["rate"])
                elif source == "compute":
                    ret["avg_Mflop/s"] = float(r["rate"])

        # Let's build the grand total of read + write
        ret["sum_total"] = ret["sum_read"] + ret["sum_write"]
        ret["avg_total"] = ret["avg_read"] + ret["avg_write"]

        return ret | self.parameters.get_result_format()


class StressNGVNNIMethods:
    class Method(NamedTuple):
        check: Callable[[BaseHardware], bool]
        parameters: list[str]

    def __init__(self):
        M = StressNGVNNIMethods.Method

        def check_support(flag: str) -> Callable[[BaseHardware], bool]:
            def check(hw: BaseHardware) -> bool:
                return flag in hw.cpu_flags()

            return check

        # We don't enumerate with stress-ng --vnni-method list because we still need to
        # be able to check for compatibility.
        self.methods = {
            # tests generic methods
            "noavx_vpaddb": M(lambda _: True, ["--vnni-method", "vpaddb"]),
            "noavx_vpdpbusd": M(lambda _: True, ["--vnni-method", "vpdpbusd"]),
            "noavx_vpdpwssd": M(lambda _: True, ["--vnni-method", "vpdpwssd"]),
            # avx512 bw, relatively common
            "avx_vpaddb512": M(
                check_support("avx512bw"),
                ["--vnni-method", "vpaddb512", "--vnni-intrinsic"],
            ),
            # avx512 vnni, Xeon 3rd gen+ and Zen4 +
            "avx_vpdpbusd512": M(
                check_support("avx512_vnni"),
                ["--vnni-method", "vpdpbusd512", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd512": M(
                check_support("avx512_vnni"),
                ["--vnni-method", "vpdpwssd512", "--vnni-intrinsic"],
            ),
            # avx vnni, Xeon 4th gen+)
            "avx_vpaddb128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpaddb128", "--vnni-intrinsic"],
            ),
            "avx_vpaddb256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpaddb256", "--vnni-intrinsic"],
            ),
            "avx_vpdpbusd128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpbusd128", "--vnni-intrinsic"],
            ),
            "avx_vpdpbusd256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpbusd256", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpwssd128", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpwssd256", "--vnni-intrinsic"],
            ),
        }

    def enumerate(self) -> Iterable[str]:
        return self.methods.keys()

    def available(self, method: str) -> bool:
        return method in self.methods

    def cpu_check(self, method: str, hw: BaseHardware) -> bool:
        return self.methods[method].check(hw)

    def parameters(self, method: str) -> list[str]:
        for name, sm in self.methods.items():
            if name == method:
                return sm.parameters
        return []

    def enumerate_cpu(self, hw: BaseHardware) -> Iterable[str]:
        """list available methods for the cpu in hw"""
        return filter(lambda m: self.cpu_check(m, hw), self.enumerate())


class StressNGVNNI(StressNG):
    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        super().__init__(engine_module, parameters)
        self.method = parameters.get_engine_module_parameter()
        self.methods = StressNGVNNIMethods()
        if not self.methods.available(self.method):
            raise LookupError(f"Unknown method {self.method}")
        if not self.methods.cpu_check(self.method, parameters.get_hw()):
            raise NotImplementedError(f"CPU does not support method {self.method}")

    def run_cmd(self) -> list[str]:
        if not self.version_compatible():
            print("WARNING: skipping benchmark, needs stress-ng >= 0.16.04")
            return ["echo", "skipped benchmark, non-compatible stress-ng"]
        return (
            super().run_cmd()
            + [
                "--vnni",
                str(self.parameters.get_engine_instances_count()),
            ]
            + self.methods.parameters(self.method)
        )

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        if not self.version_compatible():
            return {}
        return super().parse_cmd(stdout, stderr)

    def version_compatible(self) -> bool:
        engine = self.engine_module.get_engine()
        return engine.version_major() > 16 or (
            engine.version_major() == 16 and engine.version_minor() >= 4
        )


class StressNGMemrate(StressNG):
    """The StressNG Memrate memory stressor."""

    def run_cmd(self) -> list[str]:
        # TODO: handle get_pinned_cpu ; it does not necessarily make sense for this
        # benchmark, but it could be revisited once we support pinning on multiple CPUs.
        if self.engine_module.get_engine().get_version() != "0.16.04":
            raise NotImplementedError(
                "StressNGStream needs stress-ng version 0.16.04 ; "
                "later version have different --metrics vs --metrics-brief options; "
                "earlier version format memory bandwidth differently"
            )
        return super().run_cmd() + [
            "--memrate",
            str(self.parameters.get_engine_instances_count()),
        ]

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        summary_parse = re.compile(
            r"memrate .* (?P<speed>[0-9\.]+) (?P<test>[a-z0-9]+) MB per sec .*$"
        )
        out = (stdout or stderr).splitlines()

        summary = [str(line) for line in out if summary_parse.search(str(line))]

        ret = {}

        for line in summary:
            matches = summary_parse.search(line)
            if matches is not None:
                r = matches.groupdict()
                test = r["test"]
                ret[test] = {
                    "avg_speed": float(r["speed"]),
                    "sum_speed": float(r["speed"])
                    * self.parameters.get_engine_instances_count(),
                }
        return ret | self.parameters.get_result_format()
