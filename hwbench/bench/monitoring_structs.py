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

    def get_name(self):
        """Return the metric name"""
        return self.name

    def get_values(self):
        """Return the aggregated raw values"""
        return self.values

    def get_unit(self):
        """Return the unit for this metric"""
        return self.unit

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

    def __str__(self) -> str:
        return str(self.value)


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


class PowerContext(Enum):
    POWER = "Power"

    def __str__(self) -> str:
        return str(self.value)
