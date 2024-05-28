from __future__ import annotations
import pathlib
from abc import abstractmethod
from typing import Optional

from .base import BaseEnvironment
from .vendors.detect import first_matching_vendor
from .vendors.vendor import Vendor
from .cpu import CPU
from .dmi import DmiSys, DmidecodeRaw
from .lspci import Lspci, LspciBin
from ..utils.external import External_Simple


# This is the interface of Hardware
# its only use is to be able to mock the environment for testing
class BaseHardware(BaseEnvironment):
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.cpu = CPU(out_dir)
        self.cpu.detect()
        self.vendor: Vendor

    @abstractmethod
    def cpu_flags(self) -> list[str]:
        return []

    @abstractmethod
    def logical_core_count(self) -> int:
        return 0

    def get_cpu(self) -> CPU:
        return self.cpu

    def get_vendor(self) -> Vendor:
        return self.vendor


class Hardware(BaseHardware):
    def __init__(self, out_dir: pathlib.Path, monitoring_config):
        super().__init__(out_dir)
        self.dmi = DmiSys(out_dir)
        self.vendor = first_matching_vendor(out_dir, self.dmi, monitoring_config)
        self.vendor.save_bios_config()
        self.vendor.save_bmc_config()
        Lspci(out_dir).run()
        LspciBin(out_dir).run()
        DmidecodeRaw(out_dir).run()
        External_Simple(self.out_dir, ["ipmitool", "sdr"], "ipmitool-sdr")

    def dump(self) -> dict[str, Optional[str | int] | dict]:
        return {
            "dmi": self.dmi.dump(),
            "cpu": self.cpu.dump(),
            "bmc": self.vendor.get_bmc().dump(),
        }

    def cpu_flags(self) -> list[str]:
        return self.cpu.get_flags()

    def logical_core_count(self) -> int:
        return self.cpu.get_logical_cores_count()


class TestHardware(Hardware):
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir

    def set_cpu(self, cpu):
        self.cpu = cpu
        self.cpu.detect()
