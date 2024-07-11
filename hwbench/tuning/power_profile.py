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
        log = tunninglog()
        if self.skip_tuning:
            log.info("skip PerformancePowerProfile as no cpu governor detected")
            return
        pattern = re.compile("cpu[0-9]+")
        for rootpath, dirnames, filenames in os.walk("/sys/devices/system/cpu"):
            for dirname in dirnames:
                if pattern.match(dirname):
                    cpudir = pathlib.Path(rootpath) / dirname
                    file = cpudir / "cpufreq/scaling_governor"
                    previous = file.read_text(encoding="utf-8").rstrip()
                    # please read https://www.kernel.org/doc/html/latest/admin-guide/pm/cpufreq.html
                    # for more explanation
                    value = "performance"
                    log.info(
                        f"write {value} in {file}",
                        extra={
                            "value": value,
                            "previous": previous,
                            "type": "sysfs",
                            "file": str(file),
                        },
                    )
                    file.write_text(f"{value}\n")
