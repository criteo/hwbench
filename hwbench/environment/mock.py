import pathlib

from .hardware import BaseHardware


def mock_hardware(flags: list[str]) -> BaseHardware:
    class MockHardware(BaseHardware):
        def __init__(self, _):
            pass

        def dump(self):
            return {}

        def cpu_flags(self) -> list[str]:
            return flags

    return MockHardware(pathlib.Path(""))
