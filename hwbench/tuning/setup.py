from .sync import Sync


class Tuning:
    def __init__(self, out_dir):
        self.out_dir = out_dir

    def apply(self):
        Sync(self.out_dir).run()
