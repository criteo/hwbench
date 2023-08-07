from __future__ import annotations
import pathlib
from typing import Optional

from .vendors.detect import first_matching_vendor
from .dmi import DmiSys


class Hardware:
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.dmi = DmiSys(out_dir)
        v = first_matching_vendor(out_dir, self.dmi)
        v.save_bios_config()

    def dump(self) -> dict[str, Optional[str | int] | dict]:
        return self.dmi.dump()
