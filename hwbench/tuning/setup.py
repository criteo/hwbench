from .drop_caches import SysctlDropCaches
from .sync import Sync


class Tuning:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def apply(self):
        Sync(self.out_dir).run()
        SysctlDropCaches(self.out_dir).run()
