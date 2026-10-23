from __future__ import annotations

import math
from abc import ABC, abstractmethod
from enum import StrEnum

from hwbench.bench.monitoring_structs import CDUMetric, CDUSample
from hwbench.utils import helpers as h

from .monitoring_device import MonitoringDevice


class CDUProtocol(StrEnum):
    """Protocol identifiers shared by all CDU vendors and model profiles."""

    SNMP_V2C = "SNMP_V2C"
    SNMP_V3 = "SNMP_V3"


class CDU(MonitoringDevice, ABC):
    """A cooling device configured independently from the server's BMC."""

    SUPPORTED_PROTOCOLS: frozenset[CDUProtocol] = frozenset()

    def __init__(self, vendor, section: str):
        super().__init__(vendor)
        self.section = section
        config = vendor.monitoring_config_file
        protocol = config.get(section, "protocol", fallback="").strip()
        try:
            self.protocol = CDUProtocol(protocol)
        except ValueError:
            h.fatal(f"CDU {section}: protocol must be explicitly set to one of: {', '.join(CDUProtocol)}")
        if self.protocol not in self.SUPPORTED_PROTOCOLS:
            supported = ", ".join(sorted(self.SUPPORTED_PROTOCOLS))
            h.fatal(f"CDU {section}: this model does not support {self.protocol}; supported protocols: {supported}")
        self.host = config.get(section, "host", fallback="").strip()
        self.timeout = config.getfloat(section, "timeout", fallback=2)
        if not self.host:
            h.fatal(f"CDU {section}: a host is required")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            h.fatal(f"CDU {section}: timeout must be positive and finite")
        self.serialnumber = config.get(section, "serial", fallback="")

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
