import os
import json
import pathlib

from .base import BaseEnvironment
from .packages import RpmList
from ..utils.archive import copy_file, create_tar_from_directory
from ..utils.external import External_Simple


class Environment(BaseEnvironment):
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir

        (self.out_dir / "kernel-info.json").write_text(json.dumps(self.kernel_version()))
        (self.out_dir / "cmdline").write_bytes(self.kernel_cmdline())

        copy_file("/proc/config.gz", str(self.out_dir))

        self.rpms = RpmList(out_dir)
        self.rpms.run()
        self.proc_sys_info()
        self.kernel_logs()

    def dump(self):
        return {
            "kernel": self.kernel_version(),
            "kernel_cmdline": self.kernel_cmdline().decode("utf-8"),
        }

    @staticmethod
    def kernel_version():
        uname = os.uname()
        return {
            "version": uname.version,
            "release": uname.release,
            "machine": uname.machine,
            "nodename": uname.nodename,
            "sysname": uname.sysname,
        }

    @staticmethod
    def kernel_cmdline():
        return pathlib.Path("/proc/cmdline").read_bytes()

    def proc_sys_info(self):
        create_tar_from_directory(
            "/proc/sys",
            self.out_dir.joinpath("proc-sys.tar"),
        )
        create_tar_from_directory(
            "/sys/devices/system/cpu",
            self.out_dir.joinpath("sys-system-cpu.tar"),
        )

    def kernel_logs(self):
        External_Simple(
            self.out_dir,
            ["journalctl", "--boot", "-k", "-o", "json", "--no-pager"],
            "kernel-logs",
        )
