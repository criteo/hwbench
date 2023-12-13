from ....bench.monitoring_structs import (
    Power,
    PowerCategories,
    PowerContext,
    Temperature,
)
from ..vendor import Vendor, BMC


class IDRAC(BMC):
    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Thermal")

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] = {}
    ) -> dict[str, dict[str, Temperature]]:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] <= 0:
                continue
            name = t["Name"].split("Temp")[0].strip()
            pc = t["PhysicalContext"]
            if pc not in thermals:
                thermals[pc] = {}
            if t["Name"] not in thermals[pc]:
                thermals[pc][t["Name"]] = Temperature(name)
            thermals[pc][t["Name"]].add(t["ReadingCelsius"])
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Power")

    def get_oem_system(self):
        return self.get_redfish_url(
            "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/System.Embedded.1"
        )

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ):
        power_consumption = super().read_power_consumption(power_consumption)
        oem_system = self.get_oem_system()
        if "ServerPwr.1.SCViewSledPwr" in oem_system["Attributes"]:
            # ServerPwr.1.SCViewSledPwr = PowerConsumedWatts + 'SC-BMC.1.ChassisInfraPowe / nb_servers
            if (
                str(PowerCategories.SERVERINCHASSIS)
                not in power_consumption[str(PowerContext.BMC)]
            ):
                power_consumption[str(PowerContext.BMC)][
                    str(PowerCategories.SERVERINCHASSIS)
                ] = Power(str(PowerCategories.SERVERINCHASSIS))
            power_consumption[str(PowerContext.BMC)][
                str(PowerCategories.SERVERINCHASSIS)
            ].add(oem_system["Attributes"]["ServerPwr.1.SCViewSledPwr"])
        if "SC-BMC.1.ChassisInfraPower" in oem_system["Attributes"]:
            # SC-BMC.1.ChassisInfraPower = ServerPwr.1.SCViewSledPwr + 'chassis / nb_servers
            if (
                str(PowerCategories.INFRASTRUCTURE)
                not in power_consumption[str(PowerContext.BMC)]
            ):
                power_consumption[str(PowerContext.BMC)][
                    str(PowerCategories.INFRASTRUCTURE)
                ] = Power(str(PowerCategories.INFRASTRUCTURE))
            power_consumption[str(PowerContext.BMC)][
                str(PowerCategories.INFRASTRUCTURE)
            ].add(oem_system["Attributes"]["SC-BMC.1.ChassisInfraPower"])

        return power_consumption


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