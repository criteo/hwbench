from .hardware import BaseHardware


class MockHardware(BaseHardware):
    def __init__(
        self,
        flags: list[str] = [],
    ):
        self.flags = flags

    def dump(self):
        return {}

    def cpu_flags(self) -> list[str]:
        return self.flags
