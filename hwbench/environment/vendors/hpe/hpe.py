import logging
import pathlib
import re
from functools import cache
from typing import cast

from ....bench.monitoring_structs import (
    MonitorMetric,
    Power,
    PowerCategories as PowerCat,
    PowerContext,
    Temperature,
)
from ..vendor import Vendor, BMC
from .ilorest import Ilorest, IlorestServerclone, ILOREST
from ....utils import helpers as h


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

    def read_thermals(self, thermals: dict[str, dict[str, Temperature]] = {}) -> dict[str, dict[str, Temperature]]:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] <= 0:
                continue
            pc = t["PhysicalContext"]

            # Temperature metrics are named like the following :
            # 05-P1 DIMM 5-8
            # 14-VR P1 Mem 1
            # 19-BMC Zone
            match = re.search(
                r"(?P<index>[0-9.]+)-(?P<sensor>[A-Za-z0-9]*) (?P<detail>[A-Za-z0-9*]*)(?P<details>.*)$",
                t["Name"],
            )
            # Normalizing names
            if match:
                s = match.group("sensor")
                d = match.group("detail")
                de = match.group("details").strip()
                # i  s  d    de
                # 04-P1 DIMM 1-4
                sd = f"{s}{d}"

                def add(self, name):
                    super().add_monitoring_value(
                        cast(dict[str, dict[str, MonitorMetric]], thermals),
                        pc,
                        Temperature(name),
                        t["Name"],
                        t["ReadingCelsius"],
                    )

                # We don't consider all sensors for now
                # This could be updated depending on the needs
                if s == "CPU":
                    add(self, sd)
                elif s == "Inlet":
                    add(self, s)
                elif d == "DIMM":
                    # P1 DIMM 1-4
                    add(self, f"{s} {d} {de}")
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Power/")

    @cache
    def __warn_psu(self, psu_number, message):
        logging.error(f"PSU {psu_number}: {message}")

    def read_power_supplies(self, power_supplies: dict[str, dict[str, Power]] = {}) -> dict[str, dict[str, Power]]:
        """Return power supplies power from server"""
        if str(PowerContext.BMC) not in power_supplies:
            power_supplies[str(PowerContext.BMC)] = {}  # type: ignore[no-redef]
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
                        super().add_monitoring_value(
                            cast(dict[str, dict[str, MonitorMetric]], power_supplies),
                            PowerContext.BMC,
                            Power(psu_name),
                            name,
                            psu["Oem"]["Hpe"]["AveragePowerOutputWatts"],
                        )
                    else:
                        # Let's inform the user the PSU is reported as non healthy
                        self.__warn_psu(
                            psu_position,
                            f'marked as {psu_state} in {psu_status.get("Health")} state',
                        )
                    continue

            # Let's inform the user that no status was found, maybe a parsing or fw issue ?
            self.__warn_psu(psu_position, "no status or state found !")

        return power_supplies

    def read_power_consumption(self, power_consumption: dict[str, dict[str, Power]] = {}):
        oem_chassis = self.get_oem_chassis()

        # If server is not in a chassis, the default parsing is good
        # That's the case for regular ProLiant servers
        if not oem_chassis:
            return super().read_power_consumption(power_consumption)

        # But for multi-server chassis, ...
        if "HPE Apollo2000 Gen10+" in oem_chassis["Name"]:
            # On Apollo2000, the generic PowerConsumedWatts is fact SERVERINCHASSIS
            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], power_consumption),
                PowerContext.BMC,
                Power(str(PowerCat.SERVERINCHASSIS)),
                str(PowerCat.SERVERINCHASSIS),
                self.get_power().get("PowerControl")[0]["PowerConsumedWatts"],
            )

            # And extract SERVER from NodePowerWatts
            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], power_consumption),
                PowerContext.BMC,
                Power(str(PowerCat.SERVER)),
                str(PowerCat.SERVER),
                oem_chassis["Oem"]["Hpe"]["NodePowerWatts"],
            )

            # And CHASSIS from ChassisPowerWatts
            super().add_monitoring_value(
                cast(dict[str, dict[str, MonitorMetric]], power_consumption),
                PowerContext.BMC,
                Power(str(PowerCat.CHASSIS)),
                str(PowerCat.CHASSIS),
                oem_chassis["Oem"]["Hpe"]["ChassisPowerWatts"],
            )
        return power_consumption

    @cache
    def is_multinode_chassis(self) -> bool:
        return True if self.get_redfish_url("/redfish/v1/Chassis/enclosurechassis/", log_failure=False) else False

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
