from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod


# This is the interface of Environment
# its only use is to be able to mock the environment for testing and have a base type
class BaseEnvironment(ABC):
    @abstractmethod
    def __init__(self, out_dir: pathlib.Path):
        pass

    @abstractmethod
    def dump(self) -> dict[str, str | int | None | dict]:
        return {}
