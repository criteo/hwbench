import re
from typing import Any
from ..bench.parameters import BenchmarkParameters
from .stressng import EngineBase, EngineModulePinnable, StressNG


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
        summary_parse_perf = re.compile(r"memrate .* (?P<speed>[0-9\.]+) (?P<test>[a-z0-9]+) MB per sec .*$")
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
                    "sum_speed": float(r["speed"]) * self.parameters.get_engine_instances_count(),
                }  # type: ignore[assignment]
        return ret | self.parameters.get_result_format()


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
