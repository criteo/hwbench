from .hardware import Hardware
from .vendors.mock import MockVendor


class MockHardware(Hardware):
    def __init__(self, flags: list[str] = [], cores: int = 0, cpu=None):
        self.cpu = cpu
        self.flags = flags
        self.cores = cores
        self.vendor = MockVendor(None, None)
        if cpu:
            cpu.detect()

    def dump(self):
        return {}

    def cpu_flags(self) -> list[str]:
        if self.cpu:
            return super().cpu_flags()
        return self.flags

    def logical_core_count(self) -> int:
        if self.cpu:
            return super().logical_core_count()
        return self.cores
