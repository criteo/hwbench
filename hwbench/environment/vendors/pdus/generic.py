from __future__ import annotations

from hwbench.bench.monitoring_structs import Power, PowerContext
from hwbench.environment.vendors.pdu import PDU
from hwbench.utils import helpers as h


def init(vendor, pdu_section):
    return Generic(vendor, pdu_section)


class Generic(PDU):
    def __init__(self, vendor, pdu_section: str):
        super().__init__(vendor, pdu_section)
        self.outletgroup: str = self.vendor.monitoring_config_file.get(self.pdu_section, "outletgroup", fallback="")
        self.multi_separator: str = self.vendor.monitoring_config_file.get(self.pdu_section, "separator", fallback=",")
        if not self.outlet and not self.outletgroup:
            h.fatal("PDU/Generic: An outlet or an outletgroup must be defined.")

        if self.outlet and self.outletgroup:
            h.fatal("PDU/Generic: outlet and outletgroup are mutually exclusive.")

    def detect(self):
        """Detect monitoring device"""
        # In theory we should enumerate the RackPDUs instead of picking "1", but for now this works
        pdu_info = self.get_redfish_url("/redfish/v1/PowerEquipment/RackPDUs/1/")
        self.manufacturer = pdu_info.get("Manufacturer")
        self.firmware_version = pdu_info.get("FirmwareVersion")
        self.model = pdu_info.get("Model")
        self.serialnumber = pdu_info.get("SerialNumber")
        self.userlabel = pdu_info.get("UserLabel")

    def dump(self):
        dump = super().dump()
        dump["user_label"] = self.userlabel
        return dump

    def get_power_url(self, url):
        return self.get_redfish_url(url).get("PowerWatts")["Reading"]

    def get_power_total(self):
        if self.outletgroup:
            option, basepath = self.outletgroup, "/redfish/v1/PowerEquipment/RackPDUs/1/OutletGroups"
        else:
            option, basepath = self.outlet, "/redfish/v1/PowerEquipment/RackPDUs/1/Outlets"
        total = 0.0
        for opt in option.split(self.multi_separator):
            total += self.get_power_url(f"{basepath}/{opt}/")
        return total

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] | None = None
    ) -> dict[str, dict[str, Power]]:
        """Return power consumption from pdu"""
        if power_consumption is None:
            power_consumption = {}
        power_consumption = super().read_power_consumption(power_consumption)
        power_consumption[str(PowerContext.PDU)][self.get_name()].add(self.get_power_total())
        return power_consumption
