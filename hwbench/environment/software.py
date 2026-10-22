import json
import logging
import os
import pathlib

from hwbench.environment.memory import KernelMemoryInfo
from hwbench.utils.archive import copy_file, create_tar_from_directory
from hwbench.utils.external import External_Simple

from .base import BaseEnvironment
from .packages import RpmList


def kernel_config_files() -> list[pathlib.Path]:
    """The files holding the build configuration of the running kernel, by preference."""
    return [pathlib.Path("/proc/config.gz"), pathlib.Path(f"/boot/config-{os.uname().release}")]


class Environment(BaseEnvironment):
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir

        (self.out_dir / "kernel-info.json").write_text(json.dumps(self.kernel_version()))
        (self.out_dir / "cmdline").write_bytes(self.kernel_cmdline())

        self.kernel_config()

        self.memory = KernelMemoryInfo()
        self.memory.detect()

        self.rpms = RpmList(out_dir)
        self.rpms.run()
        self.proc_sys_info()
        self.kernel_logs()

    def kernel_config(self):
        """Keep the kernel build configuration: /proc/config.gz when the kernel exposes it,
        otherwise the /boot/config-<release> installed with the kernel."""
        for config in kernel_config_files():
            if config.is_file():
                copy_file(str(config), str(self.out_dir))
                return
        logging.warning(
            "Cannot find the kernel configuration in %s, ignoring",
            " or ".join(str(config) for config in kernel_config_files()),
        )

    def dump(self):
        return {
            "kernel": self.kernel_version(),
            "kernel_cmdline": self.kernel_cmdline().decode("utf-8"),
            "meminfo": self.memory.dump(),
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
        block_devices = [f for f in os.listdir("/sys/block/") if os.path.isdir(f"/sys/block/{f}")]
        for block_device in block_devices:
            create_tar_from_directory(
                f"/sys/block/{block_device}",
                self.out_dir.joinpath(f"sys-block-{block_device}.tar"),
            )

    def kernel_logs(self):
        External_Simple(
            self.out_dir,
            ["journalctl", "--boot", "-k", "-o", "json", "--no-pager"],
            "kernel-logs",
        )
