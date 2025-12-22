import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hwbench.bench.monitoring_structs import (
    MonitorMetric,
    Power,
    PowerConsumptionContext,
    Temperature,
)

from .test_vendors import PATCH_TYPES, TestVendors
from .vendors.intel.intel_bmc import IntelBMC
from .vendors.intel.intel_vendor import Intel
from .vendors.mock import MockVendor

path = pathlib.Path("")


class TestIntel(TestVendors):
    """Test Intel systems using Intel vendor with BMC/Redfish support"""

    def __init__(self, *args, **kwargs):
        super().__init__(Intel("", None, "hwbench/tests/mocked_monitoring.cfg"), *args, **kwargs)
        self.path = "tests/vendors/Intel/"

    def setUp(self):
        # setUp is called by pytest to install patches
        # Prepare the vendor specifics for Intel systems
        self.install_patch(
            "hwbench.environment.vendors.intel.intel_vendor.Intel.detect",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.bmc.BMC.run",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC.detect",
            PATCH_TYPES.RETURN_VALUE,
            None,
        )
        # Mock _get_chassis to return Avenue City chassis
        self.install_patch(
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC._get_chassis",
            PATCH_TYPES.RETURN_VALUE,
            ["/redfish/v1/Chassis/AVC_Baseboard"],
        )

        # Mock get_redfish_url to return chassis with Sensors collection
        def mock_get_redfish_url(url):
            if url == "/redfish/v1/Chassis/AVC_Baseboard":
                return {
                    "@odata.id": "/redfish/v1/Chassis/AVC_Baseboard",
                    "Id": "AVC_Baseboard",
                    "Name": "AVC Baseboard",
                    "Sensors": {"@odata.id": "/redfish/v1/Chassis/AVC_Baseboard/Sensors"},
                }
            elif url == "/redfish/v1/Chassis/AVC_Baseboard/Sensors":
                # Return the thermal data from the test file
                return self.sample(self.path + "thermal")
            return None

        self.install_patch(
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC.get_redfish_url",
            PATCH_TYPES.SIDE_EFFECT,
            mock_get_redfish_url,
        )
        self.install_patch(
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC.get_thermal",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "thermal"),
        )
        self.install_patch(
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC.get_power",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "power"),
        )
        # And finish by calling the parent setUp()
        super().setUp()

    def test_thermal(self):
        """Test thermal sensor reading from Intel Avenue City BMC

        Tests that the following sensors are properly categorized:
        - Inlet/Outlet temperatures (airflow monitoring)
        - CPU die temperatures (per-CPU thermal monitoring)
        - Memory temperatures (DIMM thermal monitoring)
        """
        expected_output = self.generic_thermal_output()
        expected_output["Intake"] = {"Inlet": Temperature("Inlet", 25)}
        expected_output["Exhaust"] = {"Outlet": Temperature("Outlet", 35)}
        expected_output["CPU"] = {
            "CPU0 Die": Temperature("CPU0 Die", 45),
            "CPU1 Die": Temperature("CPU1 Die", 43),
        }
        expected_output["Memory"] = {
            "CPU0 DIMM": Temperature("CPU0 DIMM", 38),
            "CPU1 DIMM": Temperature("CPU1 DIMM", 37),
            "DIMM A0": Temperature("DIMM A0", 39),
            "DIMM B0": Temperature("DIMM B0", 38),
        }
        super().generic_thermal_test(expected_output)

    def test_fan(self):
        """Test fan sensor reading from Intel BMC"""
        expected_output = self.generic_fan_output()
        expected_output.Fan = {
            "Fan1": MonitorMetric("Fan1", "RPM", 5000),
            "Fan2": MonitorMetric("Fan2", "RPM", 5200),
        }
        super().generic_fan_test(expected_output)

    def test_power_consumption(self):
        """Test power consumption reading from Intel BMC"""
        expected_output = self.generic_power_output()
        expected_output.BMC = {
            "Server": Power("Server", 375.0),
            "System Power Control": Power("System Power Control", 376.0),
        }
        super().generic_power_consumption_test(expected_output)

    def test_oob_power_consumption(self):
        """Test OOB (out-of-band) power consumption reading from Intel BMC"""
        expected_output = self.generic_oob_power_output()
        expected_output.BMC = {
            "Processor0 Power Control": Power("Processor0 Power Control", 81.6),
            "Processor1 Power Control": Power("Processor1 Power Control", 81.7),
            "Processors Power Control": Power("Processors Power Control", 163.4),
            "Memory0 Power Control": Power("Memory0 Power Control", 3.45),
            "Memory1 Power Control": Power("Memory1 Power Control", 3.32),
            "Memories Power Control": Power("Memories Power Control", 6.77),
        }
        super().generic_oob_power_consumption_test(expected_output)

    def test_power_supplies(self):
        """Test power supply reading from Intel BMC"""
        expected_output = self.generic_power_supplies_output()
        expected_output.BMC = {
            "PSU1": Power("PSU1", 187.5),
            "PSU2": Power("PSU2", 187.5),
        }
        super().generic_power_supplies_test(expected_output)


@pytest.mark.parametrize(
    ("sys_vendor", "product_name", "detected"),
    [
        ("Intel Corporation", "AvenueCity", True),
        ("Intel Corporation", "NUC8i7BEH", False),
        ("Intel Corporation", None, False),
        ("OEM", "AvenueCity", False),
        ("Other", "Other", False),
    ],
)
def test_detect(sys_vendor, product_name, detected):
    """An Intel server is detected on a supported platform: not on a NUC, which has no BMC."""
    dmi = SimpleNamespace(info={"sys_vendor": sys_vendor, "product_name": product_name}.get)
    assert Intel(path, dmi, "hwbench/tests/mocked_environment.cfg").detect() is detected


def test_oob_power_consumption_other_platform():
    """An Intel server other than an Avenue City reports its other PowerControl elements with their raw names."""
    power = {
        "PowerControl": [
            {"Name": "System Power Control", "PowerConsumedWatts": 300},
            {"Name": "Processors Power Control", "PowerConsumedWatts": 160},
        ]
    }
    bmc = IntelBMC(path, MockVendor(path, None))
    with (
        patch.object(IntelBMC, "_get_chassis", return_value=["/redfish/v1/Chassis/1"]),
        patch.object(IntelBMC, "get_power", return_value=power),
    ):
        reported = bmc.read_oob_power_consumption(PowerConsumptionContext()).BMC
    assert {name: metric.get_values() for name, metric in reported.items()} == {"Processors Power Control": [160]}


def test_avenue_city_detected_again():
    """An Avenue City BMC answering no chassis to an attempt is detected as one by the next attempt."""
    chassis = {"/redfish/v1/Chassis": {"Members": [{"@odata.id": "/redfish/v1/Chassis/AVC_Baseboard"}]}}
    bmc = IntelBMC(path, MockVendor(path, None))
    with patch.object(IntelBMC, "get_redfish_url", return_value={}):
        assert not bmc._check_avenue_city()
    bmc._forget_detection()
    with patch.object(IntelBMC, "get_redfish_url", side_effect=lambda url, *_: chassis.get(url, {})):
        assert bmc._check_avenue_city()
