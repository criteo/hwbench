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
        return [
            "stress-ng",
            "--qsort",
            "%d" % os.sysconf("SC_NPROCESSORS_ONLN"),
            "--timeout",
            "2",
            "--metrics-brief",
        ]

    def parse_version(self, _stdout, _stderr):
        pass

    def parse_cmd(self, stdout, _stderr):
        # TODO: better parsing than this
        score = float(stdout.splitlines()[-1].split()[7])
        return {"stress-ng bogo ops/s": score}
