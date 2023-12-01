from ..vendor import Vendor


class Dell(Vendor):
    def detect(self) -> bool:
        return self.dmi.info("sys_vendor") == "Dell Inc."

    def save_bios_config(self):
        return

    def save_bmc_config(self):
        return

    def name(self) -> str:
        return "Dell"
