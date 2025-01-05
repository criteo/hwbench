from __future__ import annotations

from hwbench.bench.monitoring_structs import Power, PowerContext
from hwbench.environment.vendors.pdu import PDU
from hwbench.utils import helpers as h


def init(vendor, pdu_section):
    return Raritan(vendor, pdu_section)


class Raritan(PDU):
    def __init__(self, vendor, pdu_section):
        super().__init__(vendor, pdu_section)
        self.outletgroup = self.vendor.monitoring_config_file.get(self.pdu_section, "outletgroup", fallback="")
        if not self.outlet and not self.outletgroup:
            h.fatal("PDU/Raritan: An outlet or an outletgroup must be defined.")

        if self.outlet and self.outletgroup:
            h.fatal("PDU/Raritan: outlet and outletgroup are mutually exclusive.")

    def detect(self):
        """Detect monitoring device"""
        pdu_info = self.get_redfish_url("/redfish/v1/PowerEquipment/RackPDUs/1/")
        self.firmware_version = pdu_info.get("FirmwareVersion")
        self.model = pdu_info.get("Model")
        self.serialnumber = pdu_info.get("SerialNumber")

    def get_power(self):
        if self.outletgroup:
            return self.get_redfish_url(f"/redfish/v1/PowerEquipment/RackPDUs/1/OutletGroups/{self.outletgroup}/")
        else:
            return self.get_redfish_url(f"/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/{self.outlet}/")

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] | None = None
    ) -> dict[str, dict[str, Power]]:
        """Return power consumption from pdu"""
        if power_consumption is None:
            power_consumption = {}
        power_consumption = super().read_power_consumption(power_consumption)
        power_consumption[str(PowerContext.PDU)][self.get_name()].add(self.get_power().get("PowerWatts")["Reading"])
        return power_consumption
