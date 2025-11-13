from __future__ import annotations

from typing import cast

from hwbench.bench.monitoring_structs import (
    MonitorMetric,
    Power,
    PowerConsumptionContext,
    PowerSuppliesContext,
    Temperature,
    ThermalContext,
)
from hwbench.bench.monitoring_structs import PowerCategories as PowerCat
from hwbench.environment.vendors.vendor import BMC, Vendor
from hwbench.utils import helpers as h


class IDRAC(BMC):
    oem_endpoint = ""

    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/System.Embedded.1/Thermal")

    def read_thermals(self, thermals: ThermalContext) -> ThermalContext:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] is None or t["ReadingCelsius"] <= 0:
                continue
            name = t["Name"].split("Temp")[0].strip()
            pc = t["PhysicalContext"]

            # Adding quirks on some models.
            # On Gen14, some PhysicalContext are not provided, let's workaround that.
            if pc is None and "Inlet" in name:
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

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        power_consumption = super().read_power_consumption(power_consumption)
        oem_system = self.get_oem_system()
        if "ServerPwr.1.SCViewSledPwr" in oem_system["Attributes"]:
            # ServerPwr.1.SCViewSledPwr is computed from other metrics
            # It includes the SLED power consumption + a mathematical portion of the chassis consumption
            # It's computed like : ServerPwr.1.SCViewSledPwr = PowerConsumedWatts + 'SC-BMC.1.ChassisInfraPower / nb_servers'
            name = str(PowerCat.SERVERINCHASSIS)
            if name not in power_consumption.BMC:
                power_consumption.BMC[name] = Power(name)
            power_consumption.BMC[name].add(oem_system["Attributes"]["ServerPwr.1.SCViewSledPwr"])

        if "SC-BMC.1.ChassisInfraPower" in oem_system["Attributes"]:
            # SC-BMC.1.ChassisInfraPower reports the power consumption of the chassis infrastructure,
            # not counting the SLEDs
            name = str(PowerCat.INFRASTRUCTURE)
            if name not in power_consumption.BMC:
                power_consumption.BMC[name] = Power(name)
            power_consumption.BMC[name].add(oem_system["Attributes"]["SC-BMC.1.ChassisInfraPower"])

        # Let's add the sum of the power supplies to get the inlet power consumption
        # It will be compared at some point with the PDU reporting.
        chassis_name = str(PowerCat.CHASSIS)
        if chassis_name not in power_consumption.BMC:
            power_consumption.BMC[chassis_name] = Power(chassis_name)
        psus = PowerSuppliesContext()
        psus = super().read_power_supplies(psus)
        power_consumption.BMC[chassis_name].add(float(sum([psu.get_values()[-1] for _, psu in psus.BMC.items()])))

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
