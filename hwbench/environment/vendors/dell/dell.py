from ..vendor import Vendor, BMC, Temperature, Power, PowerContext


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

    def get_oem_system(self):
        return self.get_redfish_url(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/System.Embedded.1"
        )

    def read_power_consumption(self):
        pc = super().read_power_consumption()
        oem_system = self.get_oem_system()
        if "ServerPwr.1.SCViewSledPwr" in oem_system["Attributes"]:
            # ServerPwr.1.SCViewSledPwr = PowerConsumedWatts + 'SC-BMC.1.ChassisInfraPowe / nb_servers
            pc[str(PowerContext.POWER)]["ServerInChassis"] = Power(
                "ServerInChassis", oem_system["Attributes"]["ServerPwr.1.SCViewSledPwr"]
            )
        if "SC-BMC.1.ChassisInfraPower" in oem_system["Attributes"]:
            # SC-BMC.1.ChassisInfraPower = ServerPwr.1.SCViewSledPwr + 'chassis / nb_servers
            pc[str(PowerContext.POWER)]["Infrastructure"] = Power(
                "Infrastructure",
                oem_system["Attributes"]["SC-BMC.1.ChassisInfraPower"],
            )

        return pc


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
