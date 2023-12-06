from ..vendor import Vendor, BMC, Temperature


class IDRAC(BMC):
    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Thermal")

    def read_thermals(self) -> dict[str, dict[str, Temperature]]:
        thermals = {}  # type: dict[str, dict[str, Temperature]]
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] <= 0:
                continue
            pc = t["PhysicalContext"]
            if pc not in thermals:
                thermals[pc] = {}
            name = t["Name"].split("Temp")[0].strip()
            thermals[pc][t["Name"]] = Temperature(name, t["ReadingCelsius"])
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Power")


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
