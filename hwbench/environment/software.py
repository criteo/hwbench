import os
import json
import pathlib

from .packages import RpmList
from ..utils.archive import create_tar_from_directory


class Environment:
    def __init__(self, out_dir):
        self.out_dir = out_dir

        (self.out_dir / "kernel-info.json").write_text(
            json.dumps(self.kernel_version())
        )
        (self.out_dir / "cmdline").write_bytes(self.kernel_cmdline())

        self.rpms = RpmList(out_dir)
        self.proc_sys_info()

    def dump(self):
        return {
            "kernel": self.kernel_version(),
            "kernel_cmdline": self.kernel_cmdline().decode("utf-8"),
            "rpms": self.rpms.run(),
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
