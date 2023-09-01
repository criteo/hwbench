import os
import pathlib
import re

from ..utils.hwlogging import tunninglog


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
            len(available_governors) == 1 and available_governors[0] == "menu"
        )

    def run(self) -> None:
        if self.skip_tuning:
            return
        pattern = re.compile("cpu[0-9]+")
        log = tunninglog()
        for rootpath, dirnames, filenames in os.walk("/sys/devices/system/cpu"):
            for dirname in dirnames:
                if pattern.match(dirname):
                    cpudir = pathlib.Path(rootpath) / dirname
                    governor = cpudir / "cpufreq/scaling_governor"
                    # please read https://www.kernel.org/doc/html/latest/admin-guide/pm/cpufreq.html
                    # for more explanation
                    value = "performance"
                    log.info(
                        f"write {value} in {governor}",
                        extra={
                            "type": "sysfs",
                            "file": str(governor),
                            "value": value,
                        },
                    )
                    (governor).write_text(f"{value}\n")
