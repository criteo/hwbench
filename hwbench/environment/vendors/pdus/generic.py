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

        self.outlets = []
        for outlet in self.get_power():
            self.outlets.append(
                {
                    "id": outlet.get("Id"),
                    "name": outlet.get("Name"),
                    "user_label": outlet.get("UserLabel"),
                }
            )

    def dump(self):
        dump = super().dump()
        dump["user_label"] = self.userlabel
        dump["outlets"] = self.outlets
        return dump

    def get_power(self):
        power = []
        if self.outletgroup:
            option, basepath = self.outletgroup, "/redfish/v1/PowerEquipment/RackPDUs/1/OutletGroups"
        else:
            option, basepath = self.outlet, "/redfish/v1/PowerEquipment/RackPDUs/1/Outlets"
        for opt in option.split(self.multi_separator):
            power.append(self.get_redfish_url(f"{basepath}/{opt}/"))

    def get_power_total(self):
        total = 0.0
        for outlet in self.get_power():
            total += outlet.get("PowerWatts")["Reading"]
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
