import os
import pathlib

from ..utils.hwlogging import tunninglog


class IOScheduler:
    def __init__(self, out_dir, scheduler):
        self.out_dir = out_dir
        self.scheduler = scheduler

    def run(self):
        log = tunninglog()
        for rootpath, dirnames, filenames in os.walk("/sys/block"):
            for dirname in dirnames:
                diskdir = pathlib.Path(rootpath) / dirname
                file = diskdir / "queue/scheduler"
                # see https://docs.kernel.org/block/switching-sched.html
                # for deeper explanation
                log.info(
                    f"write {self.scheduler} in {file}",
                    extra={
                        "type": "sysfs",
                        "file": file,
                        "value": self.scheduler,
                    },
                )
                (file).write_text(f"{self.scheduler}\n")


class MQDeadlineIOScheduler(IOScheduler):
    def __init__(self, out_dir):
        super().__init__(out_dir, "mq-deadline")
