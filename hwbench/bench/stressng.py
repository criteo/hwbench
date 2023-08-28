import abc
import pathlib
import re
from typing import Optional, Any

from ..utils.external import External
from .bench import Bench


class StressNG(External, Bench):
    @abc.abstractmethod
    def __init__(self, out_dir: pathlib.Path, timeout: int, workers: int):
        External.__init__(self, out_dir)
        Bench.__init__(self)
        self.stressor_name = "undefined"
        self.timeout = timeout
        self.workers = workers

    @property
    def name(self) -> str:
        return "stress-ng-" + self.stressor_name

    def run_cmd_version(self) -> list[str]:
        return [
            "stress-ng",
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        args = [
            "stress-ng",
            "--timeout",
            str(self.timeout),
            "--metrics-brief",
        ]
        if self.version_major() >= 16:
            args.insert(1, "--quiet")
        return args

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[2]
        return self.version

    def version_major(self) -> int:
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

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
        return {
            f"{self.name} bogo ops/s": score,
            "timeout": self.timeout,
            "workers": self.workers,
        }


class StressNGQsort(StressNG):
    def __init__(self, out_dir: pathlib.Path, timeout: int, workers: int):
        super().__init__(out_dir, timeout, workers)
        self.stressor_name = "qsort"

    def run_cmd(self) -> list[str]:
        return super().run_cmd() + [
            "--qsort",
            str(self.workers),
        ]


class StressNGCpu(StressNG):
    def __init__(self, out_dir: pathlib.Path, timeout: int, workers: int, method: str):
        super().__init__(out_dir, timeout, workers)
        self.method = method
        self.stressor_name = "cpu-" + method

    def run_cmd(self) -> list[str]:
        return super().run_cmd() + [
            "--cpu",
            str(self.workers),
            "--cpu-method",
            self.method,
        ]


class StressNGMethods(StressNG):
    def __init__(self, out_dir: pathlib.Path, timeout: int, workers: int):
        super().__init__(out_dir, timeout, workers)
        self.stressor_name = "cpu-method-list"

    def run_cmd(self) -> list[str]:
        return [
            "stress-ng",
            "--cpu-method",
            "list",
        ]

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> list[str]:
        out = (stdout or stderr).split(b":", 1)
        methods = out[1].decode("utf-8").split()
        methods.remove("all")
        return methods


class StressNGStream(StressNG):
    def __init__(
        self,
        out_dir: pathlib.Path,
        timeout: int,
        workers: int,
        stream_l3_size: Optional[int] = None,
    ):
        super().__init__(out_dir, timeout, workers)
        self.stressor_name = "stream"

        if (stream_l3_size is not None) and (stream_l3_size > 0):
            self.stream_l3_size = stream_l3_size

    def run_cmd(self) -> list[str]:
        ret: list[str] = [
            "stress-ng",
            "--timeout",
            str(self.timeout),
            "--metrics-brief",
            "--stream",
            str(self.workers),
        ]

        if self.timeout < 5:
            raise Exception("StressNGStream needs at least a 5s timeout")

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

        detail_size = self.workers or len(detail)

        ret = {
            "detail": {
                "read": [0] * detail_size,
                "write": [0] * detail_size,
                "Mflop/s": [0] * detail_size,
            },
            "read": 0,
            "write": 0,
            "Mflop/s": 0,
            "workers": self.workers,
            "timeout": self.timeout,
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

        return ret


def stress_ng_cpu_all(
    out_dir: pathlib.Path, timeout: int, workers: int
) -> dict[str, Bench]:
    methods = StressNGMethods(out_dir, timeout, workers).run()
    return dict(
        map(
            lambda m: (f"sng-{m}", StressNGCpu(out_dir, timeout, workers, m)),
            methods,
        )
    )
