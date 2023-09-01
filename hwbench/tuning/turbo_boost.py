import errno
from pathlib import Path

from ..utils.hwlogging import tunninglog


class TurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            tunninglog().info("write 1 in /sys/devices/system/cpu/cpufreq/boost")
            open("/sys/devices/system/cpu/cpufreq/boost", "w").write("1\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass


class IntelTurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            # this is not the documentation you are looking for
            # https://www.kernel.org/doc/html/v5.0/admin-guide/pm/intel_pstate.html
            file = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
            value = 0
            tunninglog().info(
                "allow the driver to set P-states",
                extra={
                    "type": "sysfs",
                    "file": str(file),
                    "value": value,
                },
            )
            (file).write_text(f"{value}\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass
