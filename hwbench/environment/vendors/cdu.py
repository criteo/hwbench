from __future__ import annotations

import math
from abc import ABC, abstractmethod
from enum import StrEnum

from hwbench.bench.monitoring_structs import MONITORING_PRECISION_S, CDUMetric, CDUSample
from hwbench.utils import helpers as h

from .monitoring_device import MonitoringDevice, section_value


class CDUProtocol(StrEnum):
    """Protocol identifiers shared by all CDU vendors and model profiles."""

    SNMP_V2C = "SNMP_V2C"
    SNMP_V3 = "SNMP_V3"


# The longest and the default timeouts of a CDU request, in seconds: the requests are made within
# the monitoring loop, so a CDU not answering must leave most of its precision to the other sources
MAX_TIMEOUT = MONITORING_PRECISION_S / 2
DEFAULT_TIMEOUT = MONITORING_PRECISION_S / 4


class CDU(MonitoringDevice, ABC):
    """A cooling device configured independently from the server's BMC."""

    SUPPORTED_PROTOCOLS: frozenset[CDUProtocol] = frozenset()

    def __init__(self, vendor, section: str):
        super().__init__(vendor)
        self.section = section
        protocol = self.config_value("protocol", "")
        try:
            self.protocol = CDUProtocol(protocol)
        except ValueError:
            h.fatal(f"CDU {section}: protocol must be explicitly set to one of: {', '.join(CDUProtocol)}")
        if self.protocol not in self.SUPPORTED_PROTOCOLS:
            supported = ", ".join(sorted(self.SUPPORTED_PROTOCOLS))
            h.fatal(f"CDU {section}: this model does not support {self.protocol}; supported protocols: {supported}")
        self.host = self.config_value("host")
        self.timeout = self.config_value("timeout", DEFAULT_TIMEOUT, float)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            h.fatal(f"CDU {section}: timeout must be positive and finite")
        if self.timeout > MAX_TIMEOUT:
            h.fatal(
                f"CDU {section}: timeout must be at most {MAX_TIMEOUT:g}s, half the monitoring precision, "
                "not to delay the monitoring loop when the CDU does not answer"
            )
        self.serialnumber = self.config_value("serial", "")

    def config_value(self, key: str, fallback=None, convert=None):
        """The value of a key of the section of the CDU, see section_value()."""
        return section_value(self.vendor.monitoring_config_file, "CDU", self.section, key, fallback, convert)

    def get_name(self) -> str:
        return self.section

    @abstractmethod
    def get_url(self) -> str:
        """Return the endpoint described by the protocol driver."""

    def dump(self) -> dict[str, str]:
        data = super().dump()
        data["type"] = "CDU"
        data["vendor"] = data.pop("manufacturer", "")
        data["protocol"] = self.protocol.value
        return data

    @abstractmethod
    def get_metrics(self) -> dict[str, CDUMetric]:
        """Return the definitions written alongside the aggregated readings."""

    @abstractmethod
    def sample(self) -> CDUSample:
        """Read one snapshot; missing values must remain missing."""
