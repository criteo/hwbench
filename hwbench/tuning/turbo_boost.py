import errno
from pathlib import Path

from ..utils.hwlogging import tunninglog


class TurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            file = Path("/sys/devices/system/cpu/cpufreq/boost")
            previous = file.read_text(encoding="utf-8").rstrip()
            # please read https://www.kernel.org/doc/Documentation/cpu-freq/boost.txt
            # for more
            value = "1"
            tunninglog().info(
                "allow boosting",
                extra={
                    "value": value,
                    "previous": previous,
                    "type": "sysfs",
                    "file": str(file),
                },
            )
            file.write_text(f"{value}a\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass


class IntelTurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            file = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
            previous = file.read_text(encoding="utf-8").rstrip()
            # this is not the documentation you are looking for
            # https://www.kernel.org/doc/html/v5.0/admin-guide/pm/intel_pstate.html
            value = "0"
            tunninglog().info(
                "allow the driver to set P-states",
                extra={
                    "value": value,
                    "previous": previous,
                    "type": "sysfs",
                    "file": str(file),
                },
            )
            file.write_text(f"{value}\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass
