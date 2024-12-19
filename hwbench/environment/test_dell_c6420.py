import pathlib
from .vendors.dell.dell import Dell
from .test_dell import TestDell
from ..bench.monitoring_structs import (
    FanContext,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerContext,
    Temperature,
    ThermalContext,
)

path = pathlib.Path("")


class TestDell6420(TestDell):
    def __init__(self, *args, **kwargs):
        super().__init__(Dell("", None, "tests/mocked_monitoring.cfg"), *args, **kwargs)
        self.path = "tests/vendors/Dell/C6420/"

    def test_thermal(self):
        expected_output = self.generic_thermal_output()
        expected_output[str(ThermalContext.INTAKE)] = {"Inlet Temp": Temperature("Inlet", 32)}
        expected_output[str(ThermalContext.CPU)] = {
            "CPU1 Temp": Temperature("CPU1", 37),
            "CPU2 Temp": Temperature("CPU2", 34),
        }

        super().generic_thermal_test(expected_output)

    def test_fan(self):
        expected_output = self.generic_fan_output()
        expected_output[str(FanContext.FAN)] = {
            "FAN1A": MonitorMetric("FAN1A", "RPM", 9288),
            "FAN1B": MonitorMetric("FAN1B", "RPM", 9718),
            "FAN2A": MonitorMetric("FAN2A", "RPM", 9288),
            "FAN2B": MonitorMetric("FAN2B", "RPM", 9718),
            "FAN3A": MonitorMetric("FAN3A", "RPM", 9288),
            "FAN3B": MonitorMetric("FAN3B", "RPM", 9718),
            "FAN4A": MonitorMetric("FAN4A", "RPM", 9288),
            "FAN4B": MonitorMetric("FAN4B", "RPM", 9718),
        }
        super().generic_fan_test(expected_output)

    def test_power_consumption(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.BMC)] = {
            str(PowerCategories.CHASSIS): Power(str(PowerCategories.CHASSIS), 378),
            str(PowerCategories.SERVER): Power(str(PowerCategories.SERVER), 53),
        }
        super().generic_power_consumption_test(expected_output)

    def test_power_supplies(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.BMC)] = {
            "PS1 Status": Power("PS1", 185.0),
            "PS2 Status": Power("PS2", 193.0),
        }
        super().generic_power_supplies_test(expected_output)
