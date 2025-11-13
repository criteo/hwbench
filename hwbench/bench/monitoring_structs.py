from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any


@dataclass
class MonitorMetric:
    """A class to represent monitoring metrics"""

    name: str
    unit: str
    value: float = field(default=sys.float_info.max, compare=False, repr=False)
    values: list[float] = field(default_factory=list, init=False)
    mean: list[float] = field(default_factory=list, init=False)
    min: list[float] = field(default_factory=list, init=False)
    max: list[float] = field(default_factory=list, init=False)
    stdev: list[float] = field(default_factory=list, init=False)
    samples: list[int] = field(default_factory=list, init=False)
    full_name: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if self.value != sys.float_info.max:
            self.add(self.value)

    def load_from_dict(self, input_data: dict[str, Any], full_name: str) -> None:
        """Load metric data from a dictionary."""
        self.full_name = full_name
        self.name = str(input_data.get("name", self.name))
        self.unit = str(input_data.get("unit", self.unit))
        self.mean = input_data.get("mean", [])
        self.min = input_data.get("min", [])
        self.max = input_data.get("max", [])
        self.stdev = input_data.get("stdev", [])
        self.samples = input_data.get("samples", [])

    def get_full_name(self) -> str:
        """Return the metric full name"""
        return self.full_name or self.name

    def get_name(self) -> str:
        """Return the metric name"""
        return self.name

    def get_values(self) -> list[float]:
        """Return the aggregated raw values"""
        return self.values

    def get_unit(self) -> str:
        """Return the unit for this metric"""
        return self.unit

    def get_min(self) -> list[float]:
        """Return the min for this metric"""
        return self.min

    def get_mean(self) -> list[float]:
        """Return the mean for this metric"""
        return self.mean

    def get_max(self) -> list[float]:
        """Return the max for this metric"""
        return self.max

    def get_samples(self) -> list[int]:
        """Return the number of samples"""
        return self.samples

    def add(self, value: float) -> None:
        """Add a single value"""
        self.values.append(value)

    def compact(self) -> None:
        """Compute new min/max/mean/stdev from values."""
        if not self.values:
            return

        self.min.append(min(self.values))
        self.max.append(max(self.values))
        self.mean.append(statistics.mean(self.values))
        self.stdev.append(statistics.stdev(self.values) if len(self.values) > 1 else 0.0)
        self.samples.append(len(self.values))
        self.values = []

    def reset(self) -> None:
        """Reset all metrics to the default."""
        self.value = sys.float_info.max
        self.values = []
        self.mean = []
        self.min = []
        self.max = []
        self.stdev = []
        self.samples = []


class Temperature(MonitorMetric):
    def __init__(self, name: str, value: float | None = None) -> None:
        super().__init__(name, "Celsius", value=value if value is not None else sys.float_info.max)


class Power(MonitorMetric):
    def __init__(self, name: str, value: float | None = None) -> None:
        super().__init__(name, "Watts", value=value if value is not None else sys.float_info.max)


class PowerCategories(Enum):
    """Power consumption categories"""

    #      4N CHASSIS            1N CHASSIS
    #  --------------------       ----------
    # | [server]  [server] |     | [server] |
    # | [server]  |server] |      ----------
    #  --------------------
    CHASSIS = "Chassis"
    INFRASTRUCTURE = "Infrastructure"
    SERVERINCHASSIS = "ServerInChassis"
    SERVER = "Server"
    PDU = "Pdu"

    def __str__(self) -> str:
        return str(self.value)

    def __eq__(self, value):
        return self.__str__() == str(value)

    @classmethod
    def list(cls) -> list[str]:
        return [member.value for member in cls]


@dataclass
class MonitoringMetadata:
    """Metadata for monitoring operations"""

    precision: float | None = None
    frequency: float | None = None
    iteration_time: float | None = None
    monitoring_time: float | None = None
    overdue_time_ms: float | None = None
    samples_count: int | None = None


class MonitoringMetadataKeys(StrEnum):
    precision = "precision"
    frequency = "frequency"
    iteration_time = "iteration_time"
    monitoring_time = "monitoring_time"
    overdue_time_ms = "overdue_time_ms"
    samples_count = "samples_count"


@dataclass
class FansContext:
    """Fans monitoring context"""

    Fan: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.Fan.values():
            metric.compact()


class FansContextKeys(StrEnum):
    Fan = "Fan"


@dataclass
class PowerConsumptionContext:
    """Power consumption monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)
    BMC: dict[str, MonitorMetric] = field(default_factory=dict)
    PDU: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.CPU.values():
            metric.compact()
        for metric in self.BMC.values():
            metric.compact()
        for metric in self.PDU.values():
            metric.compact()


class PowerConsumptionContextKeys(StrEnum):
    CPU = "CPU"
    BMC = "BMC"
    PDU = "PDU"


@dataclass
class PowerSuppliesContext:
    """Power supplies monitoring context"""

    BMC: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.BMC.values():
            metric.compact()


class PowerSuppliesContextKeys(StrEnum):
    BMC = "BMC"


ThermalContext = defaultdict[str, dict[str, MonitorMetric]]
"""Thermal monitoring context, based on Redfish output
https://redfish.dmtf.org/schemas/v1/PhysicalContext.json#/definitions/PhysicalContext
"""


def ThermalContextFactory() -> ThermalContext:
    return defaultdict(dict[str, MonitorMetric])


@dataclass
class FreqContext:
    """CPU frequency monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.CPU.values():
            metric.compact()


class FreqContextKeys(StrEnum):
    CPU = "CPU"


@dataclass
class IPCContext:
    """CPU IPC monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.CPU.values():
            metric.compact()


class IPCContextKeys(StrEnum):
    CPU = "CPU"


@dataclass
class MonitorContext:
    """Monitoring context"""

    BMC: dict[str, MonitorMetric] = field(default_factory=dict)
    PDU: dict[str, MonitorMetric] = field(default_factory=dict)
    CPU: dict[str, MonitorMetric] = field(default_factory=dict)

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for metric in self.BMC.values():
            metric.compact()
        for metric in self.PDU.values():
            metric.compact()
        for metric in self.CPU.values():
            metric.compact()


class MonitorContextKeys(StrEnum):
    BMC = "BMC"
    PDU = "PDU"
    CPU = "CPU"


@dataclass
class MonitoringContexts:
    """Container for all monitoring contexts"""

    Fans: FansContext = field(default_factory=FansContext)
    PowerConsumption: PowerConsumptionContext = field(default_factory=PowerConsumptionContext)
    PowerSupplies: PowerSuppliesContext = field(default_factory=PowerSuppliesContext)
    Thermal: ThermalContext = field(default_factory=ThermalContextFactory)
    Freq: FreqContext = field(default_factory=FreqContext)
    IPC: IPCContext = field(default_factory=IPCContext)
    Monitor: MonitorContext = field(default_factory=MonitorContext)

    def compact_all(self) -> None:
        """Compact all metrics in all contexts"""
        self.Fans.compact_all()
        self.PowerConsumption.compact_all()
        self.PowerSupplies.compact_all()
        for chassis in self.Thermal.values():
            for metric in chassis.values():
                metric.compact()
        self.Freq.compact_all()
        self.IPC.compact_all()
        self.Monitor.compact_all()


class MonitoringContextKeys(StrEnum):
    Fans = "Fans"
    PowerConsumption = "PowerConsumption"
    PowerSupplies = "PowerSupplies"
    Thermal = "Thermal"
    Freq = "Freq"
    IPC = "IPC"
    Monitor = "Monitor"


@dataclass
class MonitoringData:
    """Complete monitoring data with metadata and contexts"""

    metadata: MonitoringMetadata = field(default_factory=MonitoringMetadata)
    contexts: MonitoringContexts = field(default_factory=MonitoringContexts)
