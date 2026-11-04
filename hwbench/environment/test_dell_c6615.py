import pathlib

from hwbench.bench.monitoring_structs import (
    MonitorMetric,
    Power,
    PowerCategories,
    Temperature,
)

from .test_dell import TestDell
from .test_vendors import saved_redfish_config, vendors_tree
from .vendors.dell.dell import IDRAC, Dell
from .vendors.monitoring_device import REDACTED

path = pathlib.Path("")


class TestDell6615(TestDell):
    def __init__(self, *args, **kwargs):
        super().__init__(Dell("", None, "tests/mocked_environment.cfg"), *args, **kwargs)
        self.path = "tests/vendors/Dell/C6615/"

    def test_thermal(self):
        expected_output = self.generic_thermal_output()
        expected_output["Intake"] = {"Inlet Temp": Temperature("Inlet", 23)}
        expected_output["CPU"] = {"CPU1 Temp": Temperature("CPU1", 34)}
        super().generic_thermal_test(expected_output)

    def test_fan(self):
        expected_output = self.generic_fan_output()
        expected_output.Fan = {
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
        expected_output.BMC = {
            str(PowerCategories.CHASSIS): Power(str(PowerCategories.CHASSIS), 339),
            str(PowerCategories.SERVER): Power(str(PowerCategories.SERVER), 80),
            str(PowerCategories.SERVERINCHASSIS): Power(str(PowerCategories.SERVERINCHASSIS), 112),
            str(PowerCategories.INFRASTRUCTURE): Power(str(PowerCategories.INFRASTRUCTURE), 54),
        }
        super().generic_power_consumption_test(expected_output)

    def test_power_supplies(self):
        expected_output = self.generic_power_output()
        expected_output.BMC = {
            "PS1 Status": Power("PS1", 168.0),
            "PS2 Status": Power("PS2", 171.0),
        }
        super().generic_power_supplies_test(expected_output)


def test_save_bios_config(tmp_path):
    vendor = Dell(tmp_path, None, "hwbench/tests/mocked_environment.cfg")
    vendor.bmc = IDRAC(tmp_path, vendor)
    bios = saved_redfish_config(vendor, vendors_tree("Dell/C6615"), "save_bios_config")
    assert list(bios) == ["/redfish/v1/Systems/System.Embedded.1/Bios"]
    attributes = bios["/redfish/v1/Systems/System.Embedded.1/Bios"]["Attributes"]
    assert len(attributes) == 482
    assert attributes["AgesaVersion"] == "GenoaPI-SP5 1.0.0.A"


def test_save_bios_config_redacts_secrets(tmp_path):
    """A BIOS password, saved as its hash, does not leave the BMC."""
    tree = vendors_tree("Dell/C6615")
    bios = tree["/redfish/v1/Systems/System.Embedded.1/Bios"]
    bios["Attributes"] |= {"SHA256SetupPassword": "0123456789ABCDEF", "SHA256SetupPasswordSalt": "FEDCBA98"}
    vendor = Dell(tmp_path, None, "hwbench/tests/mocked_environment.cfg")
    vendor.bmc = IDRAC(tmp_path, vendor)
    attributes = saved_redfish_config(vendor, tree, "save_bios_config")["/redfish/v1/Systems/System.Embedded.1/Bios"][
        "Attributes"
    ]
    assert attributes["SHA256SetupPassword"] == attributes["SHA256SetupPasswordSalt"] == REDACTED
    # An unset password is kept as such
    assert attributes["SHA256SystemPassword"] == ""


def test_save_bmc_config(tmp_path):
    tree = vendors_tree("Dell/C6615")
    attributes_url = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/iDRAC.Embedded.1"
    tree[attributes_url]["Attributes"]["Users.2.SHA256Password"] = "0123456789ABCDEF"
    vendor = Dell(tmp_path, None, "hwbench/tests/mocked_environment.cfg")
    vendor.bmc = IDRAC(tmp_path, vendor)
    config = saved_redfish_config(vendor, tree, "save_bmc_config")
    manager = "/redfish/v1/Managers/iDRAC.Embedded.1"
    assert list(config) == [
        manager,
        f"{manager}/NetworkProtocol",
        f"{manager}/EthernetInterfaces",
        f"{manager}/EthernetInterfaces/NIC.1",
        f"{manager}/SerialInterfaces",
        f"{manager}/SerialInterfaces/Serial.1",
        f"{manager}/HostInterfaces",
        f"{manager}/HostInterfaces/Host.1",
        # The configuration of the iDRAC, linked from the manager
        attributes_url,
        f"{manager}/Oem/Dell/DellAttributes/System.Embedded.1",
        f"{manager}/Oem/Dell/DellAttributes/LifecycleController.Embedded.1",
    ]
    attributes = config[attributes_url]["Attributes"]
    assert len(attributes) == 1269
    assert attributes["WebServer.1.TLSProtocol"] == "TLS 1.2 and Higher"
    # The secrets of the users do not leave the BMC
    assert attributes["Users.2.SHA256Password"] == REDACTED
