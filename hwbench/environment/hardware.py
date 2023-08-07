from __future__ import annotations
import pathlib
from typing import Optional

from .dmi import DmiSys


class Hardware:
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.dmi = DmiSys(out_dir)

    def dump(self) -> dict[str, Optional[str | int] | dict]:
        return self.dmi.dump()
