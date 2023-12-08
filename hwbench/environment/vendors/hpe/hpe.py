import pathlib
import re
from ..vendor import Vendor, BMC, Temperature, Power, PowerContext
from .ilorest import Ilorest, IlorestServerclone, ILOREST


class ILO(BMC):
    def __init__(self, out_dir: pathlib.Path, vendor: Vendor, ilo: ILOREST):
        super().__init__(out_dir, vendor)
        self.ilo = ilo

    def get_ip(self) -> str:
        return self.ilo.get_ip()

    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Thermal")

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] = {}
    ) -> dict[str, dict[str, Temperature]]:
        for t in self.get_thermal().get("Temperatures"):
            if t["ReadingCelsius"] <= 0:
                continue
            pc = t["PhysicalContext"]
            if pc not in thermals:
                thermals[pc] = {}

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

                def add(name):
                    if t["Name"] not in thermals[pc]:
                        thermals[pc][t["Name"]] = Temperature(name)
                    thermals[pc][t["Name"]].add(t["ReadingCelsius"])

                # We don't consider all sensors for now
                # This could be updated depending on the needs
                if s == "CPU":
                    add(sd)
                elif s == "Inlet":
                    add(s)
                elif d == "DIMM":
                    # P1 DIMM 1-4
                    add(f"{s} {d} {de}")
        return thermals

    def get_power(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Power/")

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power supplies power from server"""
        if not power_supplies:
            power_supplies = {str(PowerContext.POWER): {}}  # type: ignore[no-redef]
        for psu in self.get_power().get("PowerSupplies"):
            # Both PSUs are named the same (HpeServerPowerSupply)
            # Let's update it to have a unique name
            name = psu["Name"] + str(psu["Oem"]["Hpe"]["BayNumber"])
            psu_name = "PS" + str(psu["Oem"]["Hpe"]["BayNumber"])
            if name not in power_supplies[str(PowerContext.POWER)]:
                power_supplies[str(PowerContext.POWER)][name] = Power(psu_name)
            power_supplies[str(PowerContext.POWER)][name].add(
                psu["Oem"]["Hpe"]["AveragePowerOutputWatts"]
            )

        return power_supplies

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ):
        power_consumption = super().read_power_consumption(power_consumption)
        oem_chassis = self.get_oem_chassis()
        if oem_chassis:
            if "Server" not in power_consumption[str(PowerContext.POWER)]:
                power_consumption[str(PowerContext.POWER)]["Server"] = Power("Server")
            power_consumption[str(PowerContext.POWER)]["Server"].add(
                oem_chassis["Oem"]["Hpe"]["NodePowerWatts"]
            )
            if "HPE Apollo2000 Gen10+" in oem_chassis["Name"]:
                # Let's compute a ServerInChassis by
                # - Collecting the chassis power consumption and divide it by the number of sleds (4)
                # - Add the difference from this average to the sled
                if "ServerInChassis" not in power_consumption[str(PowerContext.POWER)]:
                    power_consumption[str(PowerContext.POWER)][
                        "ServerInChassis"
                    ] = Power("ServerInChassis")
                power_consumption[str(PowerContext.POWER)]["ServerInChassis"].add(
                    oem_chassis["Oem"]["Hpe"]["NodePowerWatts"]
                    + (
                        (oem_chassis["Oem"]["Hpe"]["ChassisPowerWatts"] / 4)
                        - oem_chassis["Oem"]["Hpe"]["NodePowerWatts"]
                    )
                ),

        return power_consumption

    def get_oem_chassis(self):
        return self.get_redfish_url("/redfish/v1/Chassis/enclosurechassis/")


class Hpe(Vendor):
    def __init__(self, out_dir, dmi):
        self.out_dir = out_dir
        self.dmi = dmi
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
