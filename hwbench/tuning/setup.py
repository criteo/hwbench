from .drop_caches import SysctlDropCaches
from .power_profile import PerformancePowerProfile
from .scheduler import MQDeadlineIOScheduler
from .turbo_boost import IntelTurboBoost, TurboBoost
from ..utils.external import External_Simple


class Tuning:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def apply(self):
        External_Simple(self.out_dir, ["sync"])
        SysctlDropCaches(self.out_dir).run()
        PerformancePowerProfile(self.out_dir).run()
        IntelTurboBoost(self.out_dir).run()
        TurboBoost(self.out_dir).run()
        MQDeadlineIOScheduler(self.out_dir).run()
