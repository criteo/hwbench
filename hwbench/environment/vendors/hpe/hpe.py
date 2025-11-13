from __future__ import annotations

import logging
import pathlib
import re
from functools import cache
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

from .ilorest import ILOREST, Ilorest, IlorestServerclone


class ILO(BMC):
    def __init__(self, out_dir: pathlib.Path, vendor: Vendor, ilo: ILOREST):
        super().__init__(out_dir, vendor)
        self.ilo = ilo

    def get_url(self) -> str:
        # If the configuration file provides and url, let's use it
        url = self.vendor.monitoring_config_file.get(self.bmc_section, "url", fallback="")
        if url:
            return url

        ipv4 = self.ilo.get_bmc_ipv4()
        if ipv4:
            return f"https://{ipv4}"

        h.fatal("Cannot detect BMC url")

    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Thermal")

    def read_thermals(self, thermals: ThermalContext) -> ThermalContext:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] <= 0:
                continue
            pc = t["PhysicalContext"]

            # Temperature metrics are named like the following :
            # 01-Inlet Ambient
            # 02-CPU 1 PkgTmp
            # 03-CPU 2 PkgTmp
            # 04-P1 DIMM 1-6
            # 06-P1 DIMM 7-12
            # 08-P2 DIMM 1-6
            # 10-P2 DIMM 7-12
            # 12-VR P1
            # 13-VR P2
            # 14-HD Max
            # 15-AHCI HD Max
            # 16-Exp Bay Drive
            # 18-Stor Batt
            # 22-BMC
            # 23-P/S 1 Inlet
            # 24-P/S 1
            # 25-P/S 2 Inlet
            # 26-P/S 2
            # 27-E-Fuse
            # 29-Battery Zone
            # 32-PCI 1
            # 34-PCI 2
            # 36-Board Inlet
            # 39-Sys Exhaust 1
            # 40-P/S 2 Zone
            # 44-Sys Exhaust 2
            # 17.1-ExpBayBoot-I/O controller
            # 17.2-ExpBayBoot-I/O controller
            # 28.1-OCP 1-I/O module
            # 30.1-OCP 2-I/O module

            match = re.search(
                r"(?P<index>[0-9]*.?[0-9]*)-(?P<sensor>.*)$",
                t["Name"],
            )
            # Normalizing names
            if match:
                sensor = match.group("sensor").strip()  # s
                # i  < sensor  >
                # 04-P1 DIMM 1-4

                def add(self, name):
                    super().add_monitoring_value(
                        cast(dict[str, dict[str, MonitorMetric]], thermals),
                        pc,
                        Temperature(name),
                        t["Name"],
                        t["ReadingCelsius"],
                    )

                add(self, sensor)
            else:
                print(f"read_thermals: Unsupported sensor {t['Name']}")
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Power/")

    @cache
    def __warn_psu(self, psu_number, message):
        logging.error(f"PSU {psu_number}: {message}")

    def read_power_supplies(self, power_supplies: PowerSuppliesContext) -> PowerSuppliesContext:
        """Return power supplies power from server"""
        for psu in self.get_power().get("PowerSupplies"):
            psu_position = str(psu["Oem"]["Hpe"]["BayNumber"])
            # All PSUs are named the same (HpeServerPowerSupply)
            # Let's update it to have a unique name
            psu_status = psu.get("Status")
            if psu_status:
                psu_state = psu_status.get("State")
                if psu_state:
                    # We only consider healthy PSU
                    if str(psu_state).lower() == "enabled":
                        name = psu["Name"] + psu_position
                        psu_name = "PS" + psu_position
                        if name not in power_supplies.BMC:
                            power_supplies.BMC[name] = Power(psu_name)
                        power_supplies.BMC[name].add(psu["Oem"]["Hpe"]["AveragePowerOutputWatts"])
                    else:
                        # Let's inform the user the PSU is reported as non healthy
                        self.__warn_psu(
                            psu_position,
                            f"marked as {psu_state} in {psu_status.get('Health')} state",
                        )
                    continue

            # Let's inform the user that no status was found, maybe a parsing or fw issue ?
            self.__warn_psu(psu_position, "no status or state found !")

        return power_supplies

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        oem_chassis = self.get_oem_chassis()

        # If server is not in a chassis, the default parsing is good
        # That's the case for regular ProLiant servers
        if not oem_chassis:
            return super().read_power_consumption(power_consumption)

        # But for multi-server chassis, ...
        if "HPE Apollo2000 Gen10+" in oem_chassis["Name"]:
            # On Apollo2000, the generic PowerConsumedWatts is fact SERVERINCHASSIS
            server_in_chassis = str(PowerCat.SERVERINCHASSIS)
            if server_in_chassis not in power_consumption.BMC:
                power_consumption.BMC[server_in_chassis] = Power(server_in_chassis)
            power_consumption.BMC[server_in_chassis].add(self.get_power().get("PowerControl")[0]["PowerConsumedWatts"])

            # And extract SERVER from NodePowerWatts
            server = str(PowerCat.SERVER)
            if server not in power_consumption.BMC:
                power_consumption.BMC[server] = Power(server)
            power_consumption.BMC[server].add(oem_chassis["Oem"]["Hpe"]["NodePowerWatts"])

            # And CHASSIS from ChassisPowerWatts
            chassis = str(PowerCat.CHASSIS)
            if chassis not in power_consumption.BMC:
                power_consumption.BMC[chassis] = Power(chassis)
            power_consumption.BMC[chassis].add(oem_chassis["Oem"]["Hpe"]["ChassisPowerWatts"])
        return power_consumption

    @cache
    def is_multinode_chassis(self) -> bool:
        return bool(self.get_redfish_url("/redfish/v1/Chassis/enclosurechassis/", log_failure=False))

    def get_oem_chassis(self):
        if self.is_multinode_chassis():
            return self.get_redfish_url("/redfish/v1/Chassis/enclosurechassis/", log_failure=False)
        return {}


class Hpe(Vendor):
    def __init__(self, out_dir, dmi, monitoring_config_filename):
        super().__init__(out_dir, dmi, monitoring_config_filename)
        self.bmc: ILO = None
        self.ilo = None

    def detect(self) -> bool:
        return self.dmi.info("sys_vendor") == "HPE"

    def save_bios_config(self):
        Ilorest(self.out_dir).run()

    def save_bmc_config(self):
        IlorestServerclone(self.out_dir).run()

    def name(self) -> str:
        return "HPE"

    def prepare(self):
        """Prepare the Hpe object"""
        # Let's connect to the ilo and maintain a session with it
        if not self.bmc:
            self.ilo = ILOREST()
            self.ilo.login()
            self.bmc = ILO(self.out_dir, self, self.ilo)
        super().prepare()
