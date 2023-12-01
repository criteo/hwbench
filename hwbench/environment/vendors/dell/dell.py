from ..vendor import Vendor, BMC


class IDRAC(BMC):
    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Thermal")


class Dell(Vendor):
    def detect(self) -> bool:
        return self.dmi.info("sys_vendor") == "Dell Inc."

    def save_bios_config(self):
        return

    def save_bmc_config(self):
        return

    def name(self) -> str:
        return "DELL"

    def prepare(self):
        """Prepare the Dell object"""
        if not self.bmc:
            self.bmc = IDRAC(self.out_dir, self)
            self.bmc.run()
        super().prepare()
