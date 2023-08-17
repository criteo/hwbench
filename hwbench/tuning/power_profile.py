import os
import pathlib
import re


class PerformancePowerProfile:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.skip_tuning = False

        available_governors = (
            pathlib.Path("/sys/devices/system/cpu/cpuidle/available_governors")
            .read_text("ascii")
            .strip()
            .split()
        )
        self.skip_tuning |= (
            len(available_governors) == 1 & available_governors[0] == "menu"
        )

    def run(self) -> None:
        if self.skip_tuning:
            return
        pattern = re.compile("cpu[0-9]+")
        for rootpath, dirnames, filenames in os.walk("/sys/devices/system/cpu"):
            for dirname in dirnames:
                if pattern.match(dirname):
                    cpudir = pathlib.Path(rootpath) / dirname
                    (cpudir / "cpufreq/scaling_governor").write_text("performance\n")
