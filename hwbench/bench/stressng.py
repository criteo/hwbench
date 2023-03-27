import subprocess
import os

from .bench import Bench


class StressNG(Bench):
    # TODO: class settings (timeout, type of test, number of jobs, etc.)
    def run(self):
        out = subprocess.run(
            [
                "stress-ng",
                "--qsort",
                "%d" % os.sysconf("SC_NPROCESSORS_ONLN"),
                "--timeout",
                "2",
                "--metrics-brief",
            ],
            capture_output=True,
        )
        # TODO: better parsing than this
        score = float(out.stderr.splitlines()[-1].split()[8])
        return {"stress-ng bogo ops/s": score}
