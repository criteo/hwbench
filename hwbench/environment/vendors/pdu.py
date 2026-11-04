from __future__ import annotations

from hwbench.bench.monitoring_structs import MonitoringContextKeys, MonitoringContexts, Power, PowerConsumptionContext

from .monitoring_device import RedfishDevice, check_metrics, section_value


class PDU(RedfishDevice):
    def __init__(self, vendor, pdu_section: str):
        super().__init__(vendor)
        self.pdu_section = pdu_section
        self.outlet: str = self.config_value("outlet", "")

    def config_value(self, key: str, fallback=None, convert=None):
        """The value of a key of the section of the PDU, see section_value()."""
        return section_value(self.vendor.monitoring_config_file, "PDU", self.pdu_section, key, fallback, convert)

    def get_url(self):
        return self.config_value("url")

    def get_name(self) -> str:
        """Return the pdu name."""
        return self.pdu_section

    def get_label(self) -> str:
        return f"PDU {self.get_name()}"

    def initialize(self, contexts: MonitoringContexts) -> None:
        """Connect the PDU, when it is not yet, detect it and read it once."""
        if not self.logged:
            self.connect_redfish()
        self.detect()
        print(f"Monitoring/PDU: initialize {self.get_name()} with {self.get_driver_name()} {self.get_detect_string()}")
        self.read_power_consumption(contexts.PowerConsumption)
        check_metrics("PDU", MonitoringContextKeys.PowerConsumption, contexts.PowerConsumption)

    def connect_redfish(self):
        """Connect to the PDU using Redfish."""
        return super().connect_redfish(self.config_value("username"), self.config_value("password"), self.get_url())

    def get_power_total(self) -> float | None:
        """Return the power metrics, None when there is no reading."""
        return 0.0

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Return power consumption from server"""
        # Generic for now, could be override by vendors
        if self.get_name() not in power_consumption.PDU:
            power_consumption.PDU[self.get_name()] = Power(self.get_name())

        # To be completed by drivers
        return power_consumption
