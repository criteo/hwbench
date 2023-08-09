from .drop_caches import SysctlDropCaches
from .power_profile import PerformancePowerProfile
from .scheduler import MQDeadlineIOScheduler
from .sync import Sync
from .turbo_boost import IntelTurboBoost, TurboBoost


class Tuning:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def apply(self):
        Sync(self.out_dir).run()
        SysctlDropCaches(self.out_dir).run()
        PerformancePowerProfile(self.out_dir).run()
        IntelTurboBoost(self.out_dir).run()
        TurboBoost(self.out_dir).run()
        MQDeadlineIOScheduler(self.out_dir).run()
