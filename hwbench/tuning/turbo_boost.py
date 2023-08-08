import errno


class TurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            open("/sys/devices/system/cpu/cpufreq/boost", "w").write("1\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass


class IntelTurboBoost:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def run(self):
        try:
            open("/sys/devices/system/cpu/intel_pstate/no_turbo", "w").write("0\n")
        except OSError as e:  # ignore error as it might not work with current CPU
            if e.errno == errno.EACCES:
                pass
