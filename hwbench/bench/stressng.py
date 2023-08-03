import os

from .external import External


class StressNG(External):
    # TODO: class settings (timeout, type of test, number of jobs, etc.)
    def __init__(self, out_dir):
        super().__init__(out_dir)

    @property
    def name(self):
        return "stress-ng"

    def run_cmd_version(self):
        return [
            "stress-ng",
            "--version",
        ]

    def run_cmd(self):
        args = [
            "stress-ng",
            "--qsort",
            "%d" % os.sysconf("SC_NPROCESSORS_ONLN"),
            "--timeout",
            "2",
            "--metrics-brief",
        ]
        if self.version_major() >= 16:
            args.append("--quiet")
        return args

    def parse_version(self, stdout, _stderr):
        self.version = stdout.split()[2]
        return self.version

    def version_major(self):
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

    def parse_cmd(self, stdout, stderr):
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
