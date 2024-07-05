import pathlib
from .monitoring_device import MonitoringDevice
from ...utils import helpers as h
from ...utils.external import External
from ...bench.monitoring_structs import (
    FanContext,
    Power,
    PowerCategories,
    PowerContext,
    MonitorMetric,
    Temperature,
)


class BMC(MonitoringDevice, External):
    def __init__(self, out_dir: pathlib.Path, vendor):
        MonitoringDevice.__init__(self, vendor)
        External.__init__(self, out_dir)
        self.bmc = {}  # type: dict[str, str]
        self.bmc_section = None

        # For testing purposes, vendor can be None
        if self.vendor:
            bmc_sections = vendor.find_monitoring_sections("BMC")
            if bmc_sections:
                self.bmc_section = bmc_sections[0]

    def run_cmd(self) -> list[str]:
        return ["ipmitool", "lan", "print"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for row in stdout.split(b"\n"):
            if b": " in row:
                key, value = row.split(b": ", 1)
                if key.strip():
                    self.bmc[key.strip().decode("utf-8")] = value.strip().decode(
                        "utf-8"
                    )
        return self.bmc

    def run_cmd_version(self) -> list[str]:
        return ["ipmitool", "-V"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[2]
        return self.version

    @property
    def name(self) -> str:
        return "ipmitool-lan-print"

    def get_url(self) -> str:
        """Extract the BMC url."""
        # For testing purposes, vendor can be None
        if self.vendor:
            # If the configuration file provides and url, let's use it
            url = self.vendor.monitoring_config_file.get(
                self.bmc_section, "url", fallback=""
            )
            if url:
                return url

        # If no url provided, let's use the ipmi address

        try:
            return f"https://{self.bmc['IP Address']}"
        except KeyError:
            h.fatal("Cannot detect BMC url")

    def connect_redfish(self):
        """Connect to the BMC using Redfish."""
        sections = self.vendor.find_monitoring_sections(
            "BMC", [self.vendor.name(), "default"], max_sections=1
        )
        if not sections:
            h.fatal(
                "Cannot find any valid BMC entry of the monitoring configuration file"
            )

        bmc_username = self.vendor.monitoring_config_file.get(sections[0], "username")
        bmc_password = self.vendor.monitoring_config_file.get(sections[0], "password")
        return super().connect_redfish(bmc_username, bmc_password, self.get_url())

    def get_thermal(self):
        return {}

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] = {}
    ) -> dict[str, dict[str, Temperature]]:
        """Return thermals from server"""
        # To be implemented by vendors
        return {}

    def read_fans(
        self, fans: dict[str, dict[str, MonitorMetric]] = {}
    ) -> dict[str, dict[str, MonitorMetric]]:
        """Return fans from server"""
        # Generic for now, could be override by vendors
        if str(FanContext.FAN) not in fans:
            fans[str(FanContext.FAN)] = {}  # type: ignore[no-redef]
        for f in self.get_thermal().get("Fans"):
            name = f["Name"]
            if name not in fans[str(FanContext.FAN)]:
                fans[str(FanContext.FAN)][name] = MonitorMetric(
                    f["Name"], f["ReadingUnits"]
                )
            fans[str(FanContext.FAN)][name].add(f["Reading"])
        return fans

    def get_power(self):
        """Return the power metrics."""
        return {}

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power consumption from server"""
        # Generic for now, could be override by vendors
        if str(PowerContext.BMC) not in power_consumption:
            power_consumption[str(PowerContext.BMC)] = {
                str(PowerCategories.SERVER): Power(str(PowerCategories.SERVER))
            }  # type: ignore[no-redef]

        power_consumption[str(PowerContext.BMC)][str(PowerCategories.SERVER)].add(
            self.get_power().get("PowerControl")[0]["PowerConsumedWatts"]
        )
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power supplies power from server"""
        # Generic for now, could be override by vendors
        if str(PowerContext.BMC) not in power_supplies:
            power_supplies[str(PowerContext.BMC)] = {}  # type: ignore[no-redef]
        for psu in self.get_power().get("PowerSupplies"):
            psu_name = psu["Name"].split()[0]
            if psu["Name"] not in power_supplies[str(PowerContext.BMC)]:
                power_supplies[str(PowerContext.BMC)][psu["Name"]] = Power(psu_name)
            power_supplies[str(PowerContext.BMC)][psu["Name"]].add(
                psu["PowerInputWatts"]
            )
        return power_supplies

    def detect(self):
        """Detect monitoring device"""
        bmc_info = self.get_redfish_url("/redfish/v1/Managers/")
        members = bmc_info.get("Members")
        if not members:
            h.fatal("BMC: No member detected in 'Managers' endpoint")
        bmc_info = self.get_redfish_url(members[0]["@odata.id"])
        self.firmware_version = bmc_info.get("FirmwareVersion")
        self.model = bmc_info.get("Model")
