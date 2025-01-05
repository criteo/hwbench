from hwbench.environment.vendors.vendor import Vendor

from .ami_aptio import Ami_Aptio


class Amd(Vendor):
    def detect(self) -> bool:
        return self.dmi.info("sys_vendor") == "AMD Corporation"

    def save_bios_config(self):
        Ami_Aptio(self.out_dir).run()

    def save_bmc_config(self):
        return

    def name(self) -> str:
        return "AMD Corporation"
