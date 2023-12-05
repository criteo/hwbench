import pathlib
from .vendors.vendor import Temperature, MonitorMetric, ThermalContext, FanContext
from .vendors.dell.dell import Dell
from .test_vendors import TestVendors, PATCH_TYPES

path = pathlib.Path("")


class TestDell(TestVendors):
    def __init__(self, *args, **kwargs):
        super().__init__(Dell("", None), *args, **kwargs)

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
            self.sample("tests/vendors/Dell/C6615/thermal"),
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
            "Fan1A": MonitorMetric("Fan1A", 10680, "RPM"),
            "Fan1B": MonitorMetric("Fan1B", 11040, "RPM"),
            "Fan2A": MonitorMetric("Fan2A", 10680, "RPM"),
            "Fan2B": MonitorMetric("Fan2B", 10920, "RPM"),
            "Fan3A": MonitorMetric("Fan3A", 9360, "RPM"),
            "Fan3B": MonitorMetric("Fan3B", 9600, "RPM"),
            "Fan4A": MonitorMetric("Fan4A", 9360, "RPM"),
            "Fan4B": MonitorMetric("Fan4B", 9480, "RPM"),
            "Fan5A": MonitorMetric("Fan5A", 5880, "RPM"),
            "Fan5B": MonitorMetric("Fan5B", 4560, "RPM"),
        }

        super().generic_fan_test(expected_output)
