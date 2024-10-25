import statistics
import sys
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class MonitorMetric:
    """A class to represent monitoring metrics"""

    name: str
    unit: str
    # We let an option to init with an initial value
    # The default is set to None and this value shall be used during comparison or repr
    value: float = field(default=sys.float_info.max, compare=False, repr=False)
    values: list[float] = field(default_factory=list, init=False)
    mean: list[float] = field(default_factory=list, init=False)
    min: list[float] = field(default_factory=list, init=False)
    max: list[float] = field(default_factory=list, init=False)
    stdev: list[float] = field(default_factory=list, init=False)
    samples: list[float] = field(default_factory=list, init=False)

    def __post_init__(self):
        # Called after __init__
        if self.value is not None and self.value is not sys.float_info.max:
            # If a value is given, let's add it
            self.add(self.value)

    def load_from_dict(self, input: dict, full_name: str):
        self.full_name = full_name
        self.name = str(input.get("name"))
        self.unit = str(input.get("unit"))
        self.mean = input.get("mean")  # type: ignore[assignment]
        self.min = input.get("min")  # type: ignore[assignment]
        self.max = input.get("max")  # type: ignore[assignment]
        self.stdev = input.get("stdev")  # type: ignore[assignment]
        self.samples = input.get("samples")  # type: ignore[assignment]

    def get_full_name(self):
        """Return the metric full name"""
        if self.full_name:
            return self.full_name
        return self.name

    def get_name(self):
        """Return the metric name"""
        return self.name

    def get_values(self):
        """Return the aggregated raw values"""
        return self.values

    def get_unit(self):
        """Return the unit for this metric"""
        return self.unit

    def get_min(self):
        """Return the min for this metric"""
        return self.min

    def get_mean(self):
        """Return the mean for this metric"""
        return self.mean

    def get_max(self):
        """Return the max for this metric"""
        return self.max

    def get_samples(self):
        """Return the number of samples"""
        return self.samples

    def add(self, value: float):
        """Add a single value"""
        self.values.append(value)

    def compact(self):
        """Compute new min/max/mean/stdev from values."""
        # Let's compute the stats for this run
        if len(self.values):
            self.min.append(min(self.values))
            self.max.append(max(self.values))
            self.mean.append(statistics.mean(self.values))
            if len(self.values) > 1:
                self.stdev.append(statistics.stdev(self.values))
            else:
                self.stdev.append(0.0)
            self.samples.append(len(self.values))
            # And reset values so a new set of stats can be started
            self.values = []

    def reset(self):
        """Reset all metrics to the default."""
        self.value = sys.float_info.max
        self.values = []
        self.mean = []
        self.min = []
        self.max = []
        self.stdev = []
        self.samples = []


class Metrics(Enum):
    FANS = "Fans"
    POWER_CONSUMPTION = "PowerConsumption"
    POWER_SUPPLIES = "PowerSupplies"
    THERMAL = "Thermal"
    MONITOR = "Monitor"
    FREQ = "Freq"

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def list(cls):
        return list(map(lambda mm: mm.value, cls))

    @classmethod
    def list_str(cls):
        return [str(mm.value) for mm in cls]


class Temperature(MonitorMetric):
    def __init__(self, name: str, value=None):
        super().__init__(name, "Celsius", value=value)


class Power(MonitorMetric):
    def __init__(self, name: str, value=None):
        super().__init__(name, "Watts", value=value)


class ThermalContext(Enum):
    INTAKE = "Intake"
    CPU = "CPU"
    MEMORY = "Memory"
    SYSTEMBOARD = "SystemBoard"
    POWERSUPPLY = "PowerSupply"

    def __str__(self) -> str:
        return str(self.value)


class FanContext(Enum):
    FAN = "Fan"

    def __str__(self) -> str:
        return str(self.value)


class CPUContext(Enum):
    CPU = "CPU"

    def __str__(self) -> str:
        return str(self.value)


class PowerContext(Enum):
    BMC = "BMC"
    PDU = "PDU"
    CPU = "CPU"

    def __str__(self) -> str:
        return str(self.value)


class PowerCategories(Enum):
    #      4N CHASSIS            1N CHASSIS
    #  --------------------       ----------
    # | [server]  [server] |     | [server] |
    # | [server]  |server] |      ----------
    #  --------------------
    CHASSIS = "Chassis"  # The chassis power consumption
    INFRASTRUCTURE = "Infrastructure"  # = Chassis - servers (fans, pdb, ..)
    SERVERINCHASSIS = "ServerInChassis"  # One server + its part of the chassis
    SERVER = "Server"  # One server
    PDU = "Pdu"

    def __str__(self) -> str:
        return str(self.value)

    def __eq__(self, value):
        return self.__str__() == str(value)

    @classmethod
    def list(cls):
        return list(map(lambda mm: mm.value, cls))

    @classmethod
    def list_str(cls):
        return [str(mm.value) for mm in cls]


class MonitoringMetadata(Enum):
    PRECISION = "precision"
    FREQUENCY = "frequency"
    ITERATION_TIME = "iteration_time"
    MONITORING_TIME = "monitoring_time"
    OVERDUE_TIME_MS = "overdue_time_ms"
    SAMPLES_COUNT = "samples_count"

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def list(cls):
        return list(map(lambda mm: mm.value, cls))

    @classmethod
    def list_str(cls):
        return [str(mm.value) for mm in cls]
