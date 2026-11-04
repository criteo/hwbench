from __future__ import annotations

from hwbench.bench.monitoring_structs import PowerConsumptionContext
from hwbench.environment.vendors.monitoring_device import DeviceError, DeviceNotReady
from hwbench.environment.vendors.pdu import PDU
from hwbench.utils import helpers as h


def init(vendor, pdu_section):
    return Generic(vendor, pdu_section)


class Generic(PDU):
    def __init__(self, vendor, pdu_section: str):
        super().__init__(vendor, pdu_section)
        pdu_id: str = self.config_value("pdu_id", "1")
        self.redfish_root = f"/redfish/v1/PowerEquipment/RackPDUs/{pdu_id}/"
        self.outletgroup: str = self.config_value("outletgroup", "")
        self.multi_separator: str = self.config_value("separator", ",")
        if not self.outlet and not self.outletgroup:
            h.fatal(f"PDU {self.pdu_section}: outlet or outletgroup is required")

        if self.outlet and self.outletgroup:
            h.fatal(f"PDU {self.pdu_section}: outlet and outletgroup are mutually exclusive")
        self.group = self.config_value("group", "")

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
        # The configuration of the outlets is checked once, at startup: during the monitoring,
        # an outlet not answering in time only skips the reading of the iteration
        for url in self.outlet_urls():
            timeouts_before = self.timeouts
            outlet = self.get_power_outlet(url)
            if self.timeouts > timeouts_before:
                raise DeviceNotReady(f"PDU {self.pdu_section}: {self.get_url()}{url} did not answer in time")
            if not outlet or "ErrorDescription" in outlet:
                raise DeviceError(f"Cannot get outlet from url {self.get_url()}{url}, please check its name: {outlet}")
            if outlet.get("PowerWatts", {}).get("Reading") is None:
                raise DeviceError(
                    f"Outlet for {self.get_url()} does not expose power metrics: {outlet}\noutlet={self.outlet}, outletgroup={self.outletgroup}"
                )
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

    def get_power_outlet(self, url: str) -> dict:
        return self.get_redfish_url(url)

    def outlet_urls(self) -> list[str]:
        """Return the urls of the outlets, or outlet groups, the server is connected to."""
        if self.outletgroup:
            option, path = self.outletgroup, "OutletGroups"
        else:
            option, path = self.outlet, "Outlets"
        return [f"{self.redfish_root}{path}/{opt}" for opt in option.split(self.multi_separator)]

    def get_power(self) -> list[dict]:
        return [self.get_power_outlet(url) for url in self.outlet_urls()]

    def get_power_total(self) -> float | None:
        total = 0.0
        for outlet in self.get_power():
            reading = outlet.get("PowerWatts", {}).get("Reading")
            # An outlet not answering in time gives no reading: the sum of the others would be a wrong power
            if reading is None:
                return None
            total += reading
        return total

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Return power consumption from pdu"""
        power_consumption = super().read_power_consumption(power_consumption)
        power = self.get_power_total()
        if power is not None:
            power_consumption.PDU[self.get_name()].add(power)
        return power_consumption
