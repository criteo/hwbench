from .monitoring_device import MonitoringDevice
from ...utils import helpers as h
from ...bench.monitoring_structs import (
    Power,
    PowerContext,
)


class PDU(MonitoringDevice):
    def __init__(self, vendor, pdu_section):
        super().__init__(vendor)
        self.pdu_section = pdu_section
        self.outlet = self.vendor.monitoring_config_file.get(self.pdu_section, "outlet", fallback="")

    def get_url(self):
        url = super().get_url()
        if not url:
            h.fatal(f"Cannot find url for PDU {self.pdu_section}")
        return url

    def get_name(self) -> str:
        """Return the pdu name."""
        return self.pdu_section

    def connect_redfish(self):
        """Connect to the PDU using Redfish."""
        username = self.vendor.monitoring_config_file.get(self.pdu_section, "username", fallback="")
        if not username:
            h.fatal(f"Cannot find a username for PDU {self.pdu_section}")

        password = self.vendor.monitoring_config_file.get(self.pdu_section, "password", fallback="")
        if not password:
            h.fatal(f"Cannot find a password for PDU {self.pdu_section}")
        return super().connect_redfish(username, password, self.get_url())

    def get_power(self):
        """Return the power metrics."""
        return {}

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power consumption from server"""
        # Generic for now, could be override by vendors
        if str(PowerContext.PDU) not in power_consumption:
            power_consumption[str(PowerContext.PDU)] = {}  # type: ignore[no-redef]

        if self.get_name() not in power_consumption[str(PowerContext.PDU)]:
            power_consumption[str(PowerContext.PDU)][self.get_name()] = Power(self.get_name())

        # To be completed by drivers
        return power_consumption
