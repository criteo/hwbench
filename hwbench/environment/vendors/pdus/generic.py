from __future__ import annotations

from hwbench.bench.monitoring_structs import PowerConsumptionContext
from hwbench.environment.vendors.pdu import PDU
from hwbench.utils import helpers as h


def init(vendor, pdu_section):
    return Generic(vendor, pdu_section)


class Generic(PDU):
    def __init__(self, vendor, pdu_section: str):
        super().__init__(vendor, pdu_section)
        pdu_id: str = self.vendor.monitoring_config_file.get(self.pdu_section, "pdu_id", fallback="1")
        self.redfish_root = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/"
        self.outletgroup: str = self.vendor.monitoring_config_file.get(self.pdu_section, "outletgroup", fallback="")
        self.multi_separator: str = self.vendor.monitoring_config_file.get(self.pdu_section, "separator", fallback=",")
        if not self.outlet and not self.outletgroup:
            h.fatal("PDU/Generic: An outlet or an outletgroup must be defined.")

        if self.outlet and self.outletgroup:
            h.fatal("PDU/Generic: outlet and outletgroup are mutually exclusive.")
        self.group = self.vendor.monitoring_config_file.get(self.pdu_section, "group", fallback="")

    def detect(self):
        """Detect monitoring device"""
        pdu_info = self.get_redfish_url(self.redfish_root)
        self.manufacturer = pdu_info.get("Manufacturer")
        self.firmware_version = pdu_info.get("FirmwareVersion")
        self.model = pdu_info.get("Model")
        self.serialnumber = pdu_info.get("SerialNumber")
        self.userlabel = pdu_info.get("UserLabel")
        self.id = pdu_info.get("Id")

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
        dump["id"] = self.id
        if self.group:
            dump["group"] = self.group
        return dump

    def get_power_outlet(self, url: str):
        res = self.get_redfish_url(url)
        if not isinstance(res, dict) or "ErrorDescription" in res:
            h.fatal(f"Cannot get outlet from url {self.get_url()}{url}, please check its name: {res}")
        return res

    def get_power(self):
        power = []
        if self.outletgroup:
            option, path = self.outletgroup, "OutletGroups"
        else:
            option, path = self.outlet, "Outlets"
        for opt in option.split(self.multi_separator):
            power.append(self.get_power_outlet(f"{self.redfish_root}{path}/{opt}"))
        return power

    def get_power_total(self):
        total = 0.0
        for outlet in self.get_power():
            if "PowerWatts" not in outlet or "Reading" not in outlet["PowerWatts"]:
                h.fatal(
                    f"Outlet for {self.get_url()} does not expose power metrics: {outlet}\noutlet={self.outlet}, outletgroup={self.outletgroup}"
                )
            total += outlet.get("PowerWatts")["Reading"]
        return total

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Return power consumption from pdu"""
        power_consumption = super().read_power_consumption(power_consumption)
        power_consumption.PDU[self.get_name()].add(self.get_power_total())
        return power_consumption
