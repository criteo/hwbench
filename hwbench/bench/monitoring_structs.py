from __future__ import annotations

import dataclasses
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Callable


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


class UnitMetric(MonitorMetric):
    """A MonitorMetric whose unit is fixed by its class."""

    UNIT = ""

    def __init__(self, name: str, value: float | None = None) -> None:
        super().__init__(name, self.UNIT, value=sys.float_info.max if value is None else value)


class Temperature(UnitMetric):
    UNIT = "Celsius"


class Power(UnitMetric):
    UNIT = "Watts"


class Utilization(UnitMetric):
    # 'Percent' is the unit hwgraph clamps the axis of, see METRIC_AXIS.
    UNIT = "Percent"


class Memory(UnitMetric):
    UNIT = "MiB"


class Frequency(UnitMetric):
    UNIT = "Mhz"


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
    # Components metered by the BMC of a server: its memory, and the fans of the chassis cooling it
    MEMORY = "Memory"
    FANS = "Fans"
    # All the accelerators, as a whole: not named after a GPU, so the graphs of each GPU do not take it for one
    ACCELERATORS = "Accelerators"

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
class MetricContext:
    """A monitoring context: one dict of metrics per device family."""

    def compact_all(self) -> None:
        """Compact all metrics in this context"""
        for context_field in dataclasses.fields(self):
            for metric in getattr(self, context_field.name).values():
                metric.compact()


@dataclass
class FansContext(MetricContext):
    """Fans monitoring context"""

    Fan: dict[str, MonitorMetric] = field(default_factory=dict)


class FansContextKeys(StrEnum):
    Fan = "Fan"


@dataclass
class PowerConsumptionContext(MetricContext):
    """Power consumption monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)
    GPU: dict[str, MonitorMetric] = field(default_factory=dict)
    BMC: dict[str, MonitorMetric] = field(default_factory=dict)
    PDU: dict[str, MonitorMetric] = field(default_factory=dict)


class PowerConsumptionContextKeys(StrEnum):
    CPU = "CPU"
    GPU = "GPU"
    BMC = "BMC"
    PDU = "PDU"


@dataclass
class PowerSuppliesContext(MetricContext):
    """Power supplies monitoring context"""

    BMC: dict[str, MonitorMetric] = field(default_factory=dict)


class PowerSuppliesContextKeys(StrEnum):
    BMC = "BMC"


# The component family the GPU metrics are reported under: the field name of
# the fixed contexts, and the Thermal key. Shared by the all-smi and the
# Redfish readers and by hwgraph.
GPU_FAMILY = "GPU"

# Component name prefix of the cpu cores, the counterpart of GPU_FAMILY. Note
# that it is not the key the contexts split the cores under, which is 'CPU'
# (Freq.CPU holds Core_<n>): the two namespaces only coincide for the GPUs.
CORE_FAMILY = "Core"

# Component of the memory power the processors metering their DRAM report, next
# to their package power (PowerConsumption.CPU): optional, written by turbostat
# and read by hwgraph.
CPU_RAM = "Ram"


def gpu_component_name(index: int | str) -> str:
    """Monitoring component name of an accelerator.

    'GPU_<n>' mirrors the 'Core_<n>' convention used for the CPU cores, so the
    same substring filtering works on both. Shared with hwgraph, which has to
    map a benchmark's GPU list back to the metrics it produced.
    """
    return f"{GPU_FAMILY}_{index}"


# Quantity -> the GPU family of the context it belongs to. Both accelerator
# readers, all-smi host side and Redfish BMC side, report into the same places,
# so where a quantity lives is stated once here rather than once per reader.
GPU_DESTINATIONS: dict[type[UnitMetric], Callable[[MonitoringContexts], dict[str, MonitorMetric]]] = {
    Temperature: lambda contexts: contexts.Thermal[GPU_FAMILY],
    Power: lambda contexts: contexts.PowerConsumption.GPU,
    Utilization: lambda contexts: contexts.Utilization.GPU,
    Frequency: lambda contexts: contexts.Freq.GPU,
    Memory: lambda contexts: contexts.Memory.GPU,
}


ThermalContext = defaultdict[str, dict[str, MonitorMetric]]
"""Thermal monitoring context, based on Redfish output
https://redfish.dmtf.org/schemas/v1/PhysicalContext.json#/definitions/PhysicalContext
"""


def ThermalContextFactory() -> ThermalContext:
    return defaultdict(dict[str, MonitorMetric])


@dataclass
class FreqContext(MetricContext):
    """CPU and GPU frequency monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)
    GPU: dict[str, MonitorMetric] = field(default_factory=dict)


class FreqContextKeys(StrEnum):
    CPU = "CPU"
    GPU = "GPU"


@dataclass
class IPCContext(MetricContext):
    """CPU IPC monitoring context"""

    CPU: dict[str, MonitorMetric] = field(default_factory=dict)


class IPCContextKeys(StrEnum):
    CPU = "CPU"


@dataclass
class UtilizationContext(MetricContext):
    """Occupancy monitoring context"""

    GPU: dict[str, MonitorMetric] = field(default_factory=dict)


class UtilizationContextKeys(StrEnum):
    GPU = "GPU"


@dataclass
class MemoryContext(MetricContext):
    """Memory usage monitoring context"""

    GPU: dict[str, MonitorMetric] = field(default_factory=dict)


class MemoryContextKeys(StrEnum):
    GPU = "GPU"


@dataclass
class MonitorContext(MetricContext):
    """Monitoring context"""

    BMC: dict[str, MonitorMetric] = field(default_factory=dict)
    PDU: dict[str, MonitorMetric] = field(default_factory=dict)
    CPU: dict[str, MonitorMetric] = field(default_factory=dict)
    GPU: dict[str, MonitorMetric] = field(default_factory=dict)
    CDU: dict[str, MonitorMetric] = field(default_factory=dict)


class MonitorContextKeys(StrEnum):
    BMC = "BMC"
    PDU = "PDU"
    CPU = "CPU"
    GPU = "GPU"
    CDU = "CDU"


@dataclass
class MonitoringContexts:
    """Container for all monitoring contexts"""

    Fans: FansContext = field(default_factory=FansContext)
    PowerConsumption: PowerConsumptionContext = field(default_factory=PowerConsumptionContext)
    PowerSupplies: PowerSuppliesContext = field(default_factory=PowerSuppliesContext)
    Thermal: ThermalContext = field(default_factory=ThermalContextFactory)
    Freq: FreqContext = field(default_factory=FreqContext)
    IPC: IPCContext = field(default_factory=IPCContext)
    Utilization: UtilizationContext = field(default_factory=UtilizationContext)
    Memory: MemoryContext = field(default_factory=MemoryContext)
    Monitor: MonitorContext = field(default_factory=MonitorContext)

    def compact_all(self) -> None:
        """Compact all metrics in all contexts"""
        for context_field in dataclasses.fields(self):
            context = getattr(self, context_field.name)
            if isinstance(context, MetricContext):
                context.compact_all()
            else:
                # Thermal is a defaultdict keyed by Redfish PhysicalContext
                for family in context.values():
                    for metric in family.values():
                        metric.compact()


class MonitoringContextKeys(StrEnum):
    Fans = "Fans"
    PowerConsumption = "PowerConsumption"
    PowerSupplies = "PowerSupplies"
    Thermal = "Thermal"
    Freq = "Freq"
    IPC = "IPC"
    Utilization = "Utilization"
    Memory = "Memory"
    Monitor = "Monitor"


@dataclass
class CDUMetric:
    """Definition of a CDU reading, including the wire OID and conversion."""

    name: str
    oid: str
    unit: str
    scale: float = 1


@dataclass
class CDUSample:
    """One transient device response; missing readings are never zero or stale."""

    values: dict[str, float | None]
    errors: dict[str, str]


@dataclass
class CDUAggregate:
    """Statistics on the common monitoring grid; empty windows remain gaps."""

    mean: list[float | None] = field(default_factory=list)
    min: list[float | None] = field(default_factory=list)
    max: list[float | None] = field(default_factory=list)
    stdev: list[float | None] = field(default_factory=list)
    samples: list[int] = field(default_factory=list)
    errors: list[dict[str, int]] = field(default_factory=list)

    def compact(self, values: list[float], errors: dict[str, int]) -> None:
        self.mean.append(statistics.mean(values) if values else None)
        self.min.append(min(values) if values else None)
        self.max.append(max(values) if values else None)
        self.stdev.append(statistics.stdev(values) if len(values) > 1 else (0.0 if values else None))
        self.samples.append(len(values))
        self.errors.append(dict(errors))


@dataclass
class CDUMonitoringData:
    """Model definitions and aggregates sharing the host's monitoring grid."""

    timeout_s: float
    metrics: dict[str, CDUMetric]
    readings: dict[str, CDUAggregate] = field(default_factory=dict)


@dataclass
class MonitoringData:
    """Complete monitoring data with metadata and contexts"""

    metadata: MonitoringMetadata = field(default_factory=MonitoringMetadata)
    contexts: MonitoringContexts = field(default_factory=MonitoringContexts)
    cdus: dict[str, CDUMonitoringData] = field(default_factory=dict)
