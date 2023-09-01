from .hardware import BaseHardware


class MockHardware(BaseHardware):
    def __init__(
        self,
        flags: list[str] = [],
        cores: int = 0,
    ):
        self.flags = flags
        self.cores = cores

    def dump(self):
        return {}

    def cpu_flags(self) -> list[str]:
        return self.flags

    def logical_core_count(self) -> int:
        return self.cores
