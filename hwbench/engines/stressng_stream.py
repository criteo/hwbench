import re
from typing import Any, Optional

from ..bench.parameters import BenchmarkParameters
from .stressng import EngineBase, EngineModulePinnable, StressNG


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
