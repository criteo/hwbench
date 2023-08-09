import os
import pathlib


class IOScheduler:
    def __init__(self, out_dir, scheduler):
        self.out_dir = out_dir
        self.scheduler = scheduler

    def run(self):
        for rootpath, dirnames, filenames in os.walk("/sys/block"):
            for dirname in dirnames:
                diskdir = pathlib.Path(rootpath) / dirname
                (diskdir / "queue/scheduler").write_text(f"{self.scheduler}\n")


class MQDeadlineIOScheduler(IOScheduler):
    def __init__(self, out_dir):
        super().__init__(out_dir, "mq-deadline")
