from ..vendor import Vendor
from ...dmi import DmiSys
from .ilorest import Ilorest


class Hpe(Vendor):
    def detect(self) -> bool:
        self.out_dir.joinpath(DmiSys.ARCH_DMI)
        return self.dmi.info("sys_vendor") == "HPE"

    def save_bios_config(self):
        Ilorest(self.out_dir).run()
