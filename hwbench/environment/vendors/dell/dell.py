from typing import cast
from ....bench.monitoring_structs import (
    MonitorMetric,
    Power,
    PowerCategories as PowerCat,
    PowerContext,
    Temperature,
)
from ..vendor import Vendor, BMC
from ....utils import helpers as h


class IDRAC(BMC):
    oem_endpoint = ""

    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Thermal")

    def read_thermals(self, thermals: dict[str, dict[str, Temperature]] = {}) -> dict[str, dict[str, Temperature]]:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] is None or t["ReadingCelsius"] <= 0:
                continue
            name = t["Name"].split("Temp")[0].strip()
            pc = t["PhysicalContext"]

            # Adding quirks on some models
            if pc is None:
                # On Gen14, some PhysicalContext are not provided, let's workaround that.
                if "Inlet" in name:
                    pc = "Intake"

            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], thermals),
                pc,
                Temperature(name),
                t["Name"],
                t["ReadingCelsius"],
            )
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Power")

    def get_oem_system(self):
        # If we already found the proper endpoint, let's reuse it.
        if self.oem_endpoint:
            return self.get_redfish_url(
                self.oem_endpoint,
                log_failure=False,
            )

        new_oem_endpoint = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/System.Embedded.1"
        oem = self.get_redfish_url(
            new_oem_endpoint,
            log_failure=False,
        )
        # If not System.Embedded, let's use the default attributes
        if "Attributes" not in oem:
            new_oem_endpoint = "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
            oem = self.get_redfish_url(new_oem_endpoint)
            if "Attributes" not in oem:
                h.fatal("Cannot find Dell OEM metrics, please fill a bug.")

        # Let's save the endpoint to avoid trying all of them at every run
        self.oem_endpoint = new_oem_endpoint
        return oem

    def read_power_consumption(self, power_consumption: dict[str, dict[str, Power]] = {}):
        power_consumption = super().read_power_consumption(power_consumption)
        oem_system = self.get_oem_system()
        if "ServerPwr.1.SCViewSledPwr" in oem_system["Attributes"]:
            # ServerPwr.1.SCViewSledPwr is computed from other metrics
            # It includes the SLED power consumption + a mathematical portion of the chassis consumption
            # It's computed like : ServerPwr.1.SCViewSledPwr = PowerConsumedWatts + 'SC-BMC.1.ChassisInfraPower / nb_servers'
            name = str(PowerCat.SERVERINCHASSIS)
            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], power_consumption),
                PowerContext.BMC,
                Power(name),
                name,
                oem_system["Attributes"]["ServerPwr.1.SCViewSledPwr"],
            )

        if "SC-BMC.1.ChassisInfraPower" in oem_system["Attributes"]:
            # SC-BMC.1.ChassisInfraPower reports the power consumption of the chassis infrastructure,
            # not counting the SLEDs
            name = str(PowerCat.INFRASTRUCTURE)
            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], power_consumption),
                PowerContext.BMC,
                Power(name),
                name,
                oem_system["Attributes"]["SC-BMC.1.ChassisInfraPower"],
            )

        # Let's add the sum of the power supplies to get the inlet power consumption
        # It will be compared at some point with the PDU reporting.
        if str(PowerCat.CHASSIS) not in power_consumption[str(PowerContext.BMC)]:
            power_consumption[str(PowerContext.BMC)][str(PowerCat.CHASSIS)] = Power(str(PowerCat.CHASSIS))
        psus = super().read_power_supplies()
        power_consumption[str(PowerContext.BMC)][str(PowerCat.CHASSIS)].add(
            float(sum([psu.get_values()[-1] for _, psu in psus[str(PowerContext.BMC)].items()]))
        )

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
