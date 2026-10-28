from __future__ import annotations

import collections
import pathlib
from unittest.mock import patch

import pytest

from hwbench.bench.monitoring_structs import (
    MonitoringContexts,
    MonitorMetric,
    Power,
    Temperature,
)

from .test_vendors import PATCH_TYPES, TestVendors, saved_redfish_config, vendors_tree
from .vendors.bmc import BMC
from .vendors.intel.intel_bmc import IntelBMC
from .vendors.intel.intel_vendor import Intel

path = pathlib.Path("")


class TestIntel(TestVendors):
    """Test the Intel vendor on the Redfish dump of a powered-on Avenue City."""

    def __init__(self, *args, **kwargs):
        super().__init__(Intel("", None, "hwbench/tests/mocked_environment.cfg"), *args, **kwargs)

    def setUp(self):
        # setUp is called by pytest to install patches
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
            "hwbench.environment.vendors.intel.intel_bmc.IntelBMC.get_redfish_url",
            PATCH_TYPES.SIDE_EFFECT,
            lambda url, *_: REDFISH_TREE.get(url),
        )
        # And finish by calling the parent setUp()
        super().setUp()

    def test_thermal(self):
        expected_output = self.generic_thermal_output()
        expected_output["CPU"] = {
            "Die CPU1": Temperature("AVC_Baseboard-Die CPU1", 35.86),
            "Die CPU2": Temperature("AVC_Baseboard-Die CPU2", 38.797),
        }
        expected_output["Intake"] = {
            "Inlet BRD Temp": Temperature("AVC_Baseboard-Inlet BRD", 24.937),
        }
        expected_output["Memory"] = {
            "Left DIMM Bank Temp": Temperature("AVC_Baseboard-Left DIMM Bank", 26.437),
            "Right DIMM Bank Temp": Temperature("AVC_Baseboard-Right DIMM Bank", 28.437),
        }
        super().generic_thermal_test(expected_output)

    def test_fan(self):
        expected_output = self.generic_fan_output()
        expected_output.Fan = {
            "PSU1 Fan Speed 1": MonitorMetric("PSU1 Fan Speed 1", "RPM", 8192.0),
            "PSU1 Fan Speed 2": MonitorMetric("PSU1 Fan Speed 2", "RPM", 6976.0),
            "PSU2 Fan Speed 1": MonitorMetric("PSU2 Fan Speed 1", "RPM", 8192.0),
            "PSU2 Fan Speed 2": MonitorMetric("PSU2 Fan Speed 2", "RPM", 7008.0),
            "Fan 1": MonitorMetric("Fan 1", "RPM", 11843.0),
            "Fan 10": MonitorMetric("Fan 10", "RPM", 11843.0),
            "Fan 11": MonitorMetric("Fan 11", "RPM", 11843.0),
            "Fan 12": MonitorMetric("Fan 12", "RPM", 11843.0),
            "Fan 2": MonitorMetric("Fan 2", "RPM", 11988.0),
            "Fan 3": MonitorMetric("Fan 3", "RPM", 11843.0),
            "Fan 4": MonitorMetric("Fan 4", "RPM", 11988.0),
            "Fan 5": MonitorMetric("Fan 5", "RPM", 11988.0),
            "Fan 6": MonitorMetric("Fan 6", "RPM", 11843.0),
            "Fan 7": MonitorMetric("Fan 7", "RPM", 11843.0),
            "Fan 8": MonitorMetric("Fan 8", "RPM", 11843.0),
            "Fan 9": MonitorMetric("Fan 9", "RPM", 11843.0),
        }
        super().generic_fan_test(expected_output)

    def test_power_consumption(self):
        expected_output = self.generic_power_output()
        expected_output.CPU = {
            "Processor0": Power("Processor0", 39.385989552376046),
            "Processor1": Power("Processor1", 45.78143287431141),
            "CPU": Power("CPU", 85.30134929422557),
        }
        expected_output.BMC = {
            "Server": Power("Server", 216.63231438241223),
            "Memory0": Power("Memory0", 2.7243394274178594),
            "Memory1": Power("Memory1", 2.93665204668058),
            "Memory": Power("Memory", 5.654182944186493),
        }
        super().generic_power_consumption_test(expected_output)

    def test_oob_power_consumption(self):
        """Avenue City reports its power controls through read_power_consumption(), with their cleaned names."""
        super().generic_oob_power_consumption_test(self.generic_oob_power_output())

    def test_power_supplies(self):
        expected_output = self.generic_power_supplies_output()
        expected_output.BMC = {
            "PSU2": Power("PSU2", 129.0),
            "PSU1": Power("PSU1", 124.0),
        }
        super().generic_power_supplies_test(expected_output)


REDFISH_TREE = vendors_tree("Intel/AvenueCity")


def intel_vendor(out_dir: pathlib.Path) -> Intel:
    """Return an Intel vendor with an Intel BMC."""
    vendor = Intel(out_dir, None, "hwbench/tests/mocked_environment.cfg")
    vendor.bmc = IntelBMC(out_dir, vendor)
    return vendor


def avenue_city_metrics(bmc: type[BMC] = IntelBMC, tree: dict | None = None) -> MonitoringContexts:
    """Return the metrics a BMC driver reads from the Redfish dump of a powered-on Avenue City, or from <tree>."""
    tree = REDFISH_TREE if tree is None else tree
    vendor = intel_vendor(pathlib.Path(""))
    vendor.bmc = bmc(pathlib.Path(""), vendor)
    with patch.object(bmc, "get_redfish_url", side_effect=lambda url, *_: tree.get(url)):
        return vendor.get_bmc().read_metrics(MonitoringContexts())


@pytest.mark.parametrize("bmc", [IntelBMC, BMC])
def test_power_supplies_input_power(bmc):
    """The input power of the power supplies is read from their OpenBMC sensors, by the generic driver too."""
    power_supplies = avenue_city_metrics(bmc).PowerSupplies.BMC
    assert {psu: metric.get_values() for psu, metric in power_supplies.items()} == {"PSU1": [124.0], "PSU2": [129.0]}


def test_sensors_read_once_when_detected():
    """The detections of the sensors to monitor read every sensor of the chassis once, not once each."""
    requests: collections.Counter = collections.Counter()

    def get(url, *_):
        requests[url] += 1
        return REDFISH_TREE.get(url)

    bmc = BMC(pathlib.Path(""), None)
    with patch.object(BMC, "get_redfish_url", side_effect=get):
        assert bmc._get_psu_input_sensors()
        assert not bmc._get_gpu_sensors()
    sensors = [url for url in REDFISH_TREE if "/Sensors/" in url]
    assert {url: requests[url] for url in sensors} == dict.fromkeys(sensors, 1)


def test_save_bios_config(tmp_path):
    bios = saved_redfish_config(intel_vendor(tmp_path), REDFISH_TREE, "save_bios_config")
    assert list(bios) == ["/redfish/v1/Systems/system/Bios"]
    assert bios["/redfish/v1/Systems/system/Bios"]["Attributes"]["ARIEnable"] == "0x01"


def test_save_bmc_config(tmp_path):
    config = saved_redfish_config(intel_vendor(tmp_path), REDFISH_TREE, "save_bmc_config")
    assert list(config) == [
        "/redfish/v1/Managers/bmc",
        "/redfish/v1/Managers/bmc/NetworkProtocol",
        "/redfish/v1/Managers/bmc/EthernetInterfaces",
        "/redfish/v1/Managers/bmc/EthernetInterfaces/eth0",
        "/redfish/v1/Managers/bmc/EthernetInterfaces/eth1",
    ]
    # The OEM configuration of the manager, like the fan profile of OpenBMC, comes with it
    assert config["/redfish/v1/Managers/bmc"]["Oem"]["OpenBmc"]["Fan"]["Profile"] == "Performance"


def test_save_config_without_bmc(tmp_path):
    """Without BMC in the environment file, nothing is read nor saved."""
    vendor = intel_vendor(tmp_path)
    vendor.bmc.bmc_section = None
    with patch.object(IntelBMC, "connect_redfish") as connect:
        vendor.save_bios_config()
    connect.assert_not_called()
    assert not list(tmp_path.iterdir())
