import pathlib
from .vendors.vendor import (
    Power,
    Temperature,
    MonitorMetric,
    ThermalContext,
    FanContext,
    PowerContext,
)
from .vendors.dell.dell import Dell
from .test_vendors import TestVendors, PATCH_TYPES

path = pathlib.Path("")


class TestDell(TestVendors):
    def __init__(self, *args, **kwargs):
        super().__init__(Dell("", None), *args, **kwargs)
        self.path = "tests/vendors/Dell/C6615/"

    def setUp(self):
        # setUp is called by pytest to install patches
        # Prepare the vendor specifics
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.Dell.detect",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.run",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_thermal",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "thermal"),
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_power",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "power"),
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_oem_system",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "oem_system"),
        )
        # And finish by calling the parent setUp()
        super().setUp()

    def test_thermal(self):
        expected_output = self.generic_thermal_output()
        expected_output[str(ThermalContext.INTAKE)] = {
            "Inlet Temp": Temperature("Inlet", 23)
        }
        expected_output[str(ThermalContext.CPU)] = {
            "CPU1 Temp": Temperature("CPU1", 34)
        }
        super().generic_thermal_test(expected_output)

    def test_fan(self):
        expected_output = self.generic_fan_output()
        expected_output[str(FanContext.FAN)] = {
            "Fan1A": MonitorMetric("Fan1A", "RPM", 10680),
            "Fan1B": MonitorMetric("Fan1B", "RPM", 11040),
            "Fan2A": MonitorMetric("Fan2A", "RPM", 10680),
            "Fan2B": MonitorMetric("Fan2B", "RPM", 10920),
            "Fan3A": MonitorMetric("Fan3A", "RPM", 9360),
            "Fan3B": MonitorMetric("Fan3B", "RPM", 9600),
            "Fan4A": MonitorMetric("Fan4A", "RPM", 9360),
            "Fan4B": MonitorMetric("Fan4B", "RPM", 9480),
            "Fan5A": MonitorMetric("Fan5A", "RPM", 5880),
            "Fan5B": MonitorMetric("Fan5B", "RPM", 4560),
        }
        super().generic_fan_test(expected_output)

    def test_power_consumption(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.POWER)] = {
            "Chassis": Power("Chassis", 80),
            "Server": Power("Server", 54),
            "ServerInChassis": Power("ServerInChassis", 112),
            "Infrastructure": Power("Infrastructure", 54),
        }
        super().generic_power_consumption_test(expected_output)

    def test_power_supplies(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.POWER)] = {
            "PS1 Status": Power("PS1", 168.0),
            "PS2 Status": Power("PS2", 171.0),
        }
        super().generic_power_supplies_test(expected_output)
