import os
import pathlib

from ..utils.external import External
from .bench import Bench


class StressNG(External, Bench):
    # TODO: class settings (timeout, type of test, number of jobs, etc.)
    def __init__(self, out_dir: pathlib.Path):
        External.__init__(self, out_dir)
        Bench.__init__(self)

    @property
    def name(self) -> str:
        return "stress-ng"

    def run_cmd_version(self) -> list[str]:
        return [
            "stress-ng",
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        args = [
            "stress-ng",
            "--qsort",
            "%d" % os.sysconf("SC_NPROCESSORS_ONLN"),
            "--timeout",
            "2",
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
        return {"stress-ng bogo ops/s": score}
