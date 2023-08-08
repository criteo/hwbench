import os
import pathlib
import re


class PerformancePowerProfile:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        pattern = re.compile("cpu[0-9]+")
        for rootpath, dirnames, filenames in os.walk("/sys/devices/system/cpu"):
            for dirname in dirnames:
                if pattern.match(dirname):
                    cpudir = pathlib.Path(rootpath) / dirname
                    (cpudir / "cpufreq/scaling_governor").write_text("performance\n")
