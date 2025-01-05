from hwbench.utils.external import External_Simple
from hwbench.utils.hwlogging import tunninglog

from .drop_caches import SysctlDropCaches
from .power_profile import PerformancePowerProfile
from .scheduler import MQDeadlineIOScheduler
from .turbo_boost import IntelTurboBoost, TurboBoost


class Tuning:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def apply(self, apply_tuning: bool):
        if not apply_tuning:
            tunninglog().info("Tunning has been disabled on the hwbench command line")
            return
        External_Simple(self.out_dir, ["sync"])
        SysctlDropCaches(self.out_dir).run()
        PerformancePowerProfile(self.out_dir).run()
        IntelTurboBoost(self.out_dir).run()
        TurboBoost(self.out_dir).run()
        MQDeadlineIOScheduler(self.out_dir).run()
