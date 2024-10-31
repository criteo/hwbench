import re
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
        return ""


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

    def fully_skipped_job(self, p) -> bool:
        return StressNGQsort(self, p).fully_skipped_job()


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

    def fully_skipped_job(self, p) -> bool:
        return StressNGMemrate(self, p).fully_skipped_job()


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
            return f"{msg}; StressNGStream needs at least a 5s of run time"
        return msg

    def fully_skipped_job(self, p) -> bool:
        return StressNGStream(self, p).fully_skipped_job()


class EngineModuleVNNI(EngineModulePinnable):
    """This class implements the VNNI EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.methods = StressNGVNNIMethods()
        for method in self.methods.enumerate():
            self.add_module_parameter(method)

    def fully_skipped_job(self, p) -> bool:
        return StressNGVNNI(self, p).fully_skipped_job()

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run()

    def validate_module_parameters(self, params: BenchmarkParameters):
        msg = super().validate_module_parameters(params)
        method = params.get_engine_module_parameter()
        if not self.methods.available(method):
            msg += f"Unknown method {method}\n"
        if not self.methods.cpu_check(method, params.get_hw()):
            print(f"WARNING: CPU does not support method {method}, perf will be 0")
        return msg


class Engine(EngineBase):
    """The main stressn2 class."""

    def __init__(self):
        from .stressng_cpu import EngineModuleCpu

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

    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
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
            print(
                f"WARNING: skipping benchmark {self.name}, needs stress-ng >= 0.17.04"
            )
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
        skip = self.need_skip_because_version()
        if skip:
            return skip
        ret: list[str] = [
            self.engine_module.get_engine().get_binary(),
            "--timeout",
            str(self.parameters.get_runtime()),
            "--metrics",
            "--stream",
            str(self.parameters.get_engine_instances_count()),
        ]

        self.stream_l3_size: Optional[int] = None
        if self.stream_l3_size is not None:
            ret.extend(["--stream-l3-size", str(self.stream_l3_size)])
        return ret

    def empty_result(self):
        detail_size = self.parameters.get_engine_instances_count()
        return {
            "detail": {
                "read": [0] * detail_size,
                "write": [0] * detail_size,
                "Mflop/s": [0] * detail_size,
            },
            "avg_read": 0.0,
            "avg_write": 0.0,
            "avg_Mflop/s": 0.0,
            "avg_total": 0.0,
            "sum_read": 0.0,
            "sum_write": 0.0,
            "sum_Mflop/s": 0.0,
            "sum_total": 0.0,
            "skipped": True,
            "effective_runtime": 0.0,
        }

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        if self.skip:
            return self.parameters.get_result_format() | self.empty_result()
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

        ret: dict[str, Any] = {
            "detail": {
                "read": [0] * detail_size,
                "write": [0] * detail_size,
                "Mflop/s": [0] * detail_size,
            },
            "avg_read": 0.0,
            "avg_write": 0.0,
            "avg_Mflop/s": 0.0,
            "avg_total": 0.0,
            "sum_read": 0.0,
            "sum_write": 0.0,
            "sum_Mflop/s": 0.0,
            "sum_total": 0.0,
            "effective_runtime": 0.0,
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

            stats = self.stats_parse().search(line)
            if stats:
                ret["effective_runtime"] = float(stats["real_time"])

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
        self, engine_module: EngineModuleVNNI, parameters: BenchmarkParameters
    ):
        super().__init__(engine_module, parameters)
        self.method = parameters.get_engine_module_parameter()
        self.methods = engine_module.methods
        if not self.methods.available(self.method):
            raise LookupError(f"Unknown method {self.method}")
        if not self.methods.cpu_check(self.method, parameters.get_hw()):
            self.skip = True

    def run_cmd(self) -> list[str]:
        skip = self.need_skip_because_version()
        if skip:
            return skip
        return (
            super().run_cmd()
            + [
                "--vnni",
                str(self.parameters.get_engine_instances_count()),
            ]
            + self.methods.parameters(self.method)
        )

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return super().parse_cmd(stdout, stderr)


class StressNGMemrate(StressNG):
    """The StressNG Memrate memory stressor."""

    def run_cmd(self) -> list[str]:
        # TODO: handle get_pinned_cpu ; it does not necessarily make sense for this
        # benchmark, but it could be revisited once we support pinning on multiple CPUs.
        skip = self.need_skip_because_version()
        if skip:
            return skip
        return super().run_cmd() + [
            "--memrate",
            str(self.parameters.get_engine_instances_count()),
            "--memrate-flush",
        ]

    def empty_result(self):
        ret = {}
        for method in [
            "read1024",
            "read128",
            "read128pf",
            "read16",
            "read256",
            "read32",
            "read512",
            "read64",
            "read64pf",
            "read8",
            "write1024",
            "write128",
            "write128nt",
            "write16",
            "write16stod",
            "write256",
            "write32",
            "write32nt",
            "write32stow",
            "write512",
            "write64",
            "write64nt",
            "write64stoq",
            "write8",
            "write8stob",
        ]:
            ret[method] = {
                "avg_speed": 0.0,
                "sum_speed": 0.0,
                "effective_runtime": 0.0,
            }
        ret["skipped"] = True
        return ret

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        if self.skip:
            return self.parameters.get_result_format() | self.empty_result()
        summary_parse = re.compile(r"memrate .*")
        summary_parse_perf = re.compile(
            r"memrate .* (?P<speed>[0-9\.]+) (?P<test>[a-z0-9]+) MB per sec .*$"
        )
        out = (stdout or stderr).splitlines()

        summary = [str(line) for line in out if summary_parse.search(str(line))]

        ret = {}

        for line in summary:
            stats = self.stats_parse().search(line)
            if stats:
                ret["effective_runtime"] = float(stats["real_time"])
            matches = summary_parse_perf.search(line)
            if matches is not None:
                r = matches.groupdict()
                test = r["test"]
                ret[test] = {
                    "avg_speed": float(r["speed"]),
                    "sum_speed": float(r["speed"])
                    * self.parameters.get_engine_instances_count(),
                }  # type: ignore[assignment]
        return ret | self.parameters.get_result_format()
