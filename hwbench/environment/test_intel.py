from __future__ import annotations

import collections
import os
import pathlib
from collections.abc import Callable
from types import SimpleNamespace
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
        expected_output["SystemBoard"] = {
            "BMC Temp": Temperature("AVC_Baseboard-BMC", 31.562),
            "Left Mid Board Temp": Temperature("AVC_Baseboard-Left Mid Board", 28.437),
            "Left Rear Board Temp": Temperature("AVC_Baseboard-Left Rear Board", 27.375),
            "Right Mid Board Temp": Temperature("AVC_Baseboard-Right Mid Board", 29.375),
            "Right Rear Board Temp": Temperature("AVC_Baseboard-Right Rear Board", 29.312),
            "Front Panel Temp": Temperature("Intel_Front_Panel-Front Panel", 24.062),
        }
        expected_output["VoltageRegulator"] = {
            "CPU1 PVCCA Controller Temp": Temperature("AVC_Baseboard-CPU1 PVCCA Controller", 31.0),
            "CPU1 PVCCA EHV Temperature": Temperature("AVC_Baseboard-CPU1 PVCCA EHV", 32.0),
            "CPU1 PVCCD0 Temperature": Temperature("AVC_Baseboard-CPU1 PVCCD0", 33.0),
            "CPU1 PVCCFA Controller Temp": Temperature("AVC_Baseboard-CPU1 PVCCFA Controller", 32.0),
            "CPU1 PVCCFA EHV FIVRA Temperature": Temperature("AVC_Baseboard-CPU1 PVCCFA EHV FIVRA", 33.0),
            "CPU1 VCCIN Temperature": Temperature("AVC_Baseboard-CPU1 VCCIN", 36.0),
            "CPU2 PVCCA Controller Temp": Temperature("AVC_Baseboard-CPU2 PVCCA Controller", 31.0),
            "CPU2 PVCCA EHV Temperature": Temperature("AVC_Baseboard-CPU2 PVCCA EHV", 31.0),
            "CPU2 PVCCD0 Temperature": Temperature("AVC_Baseboard-CPU2 PVCCD0", 33.0),
            "CPU2 PVCCFA Controller Temp": Temperature("AVC_Baseboard-CPU2 PVCCFA Controller", 33.0),
            "CPU2 PVCCFA EHV FIVRA Temperature": Temperature("AVC_Baseboard-CPU2 PVCCFA EHV FIVRA", 33.0),
            "CPU2 VCCIN Temperature": Temperature("AVC_Baseboard-CPU2 VCCIN", 36.0),
        }
        expected_output["CPU"] = {
            "DTS CPU1": Temperature("AVC_Baseboard-DTS CPU1", 36.157),
            "DTS CPU2": Temperature("AVC_Baseboard-DTS CPU2", 39.016),
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
        expected_output["PowerSupply"] = {
            "PSU1 Temperature": Temperature("AVC_Baseboard-PSU1", 25.0),
            "PSU2 Temperature": Temperature("AVC_Baseboard-PSU2", 25.875),
        }
        expected_output["Exhaust"] = {
            "Exit Air Temp": Temperature("R4000_Chassis-Exit Air", 40.0),
        }
        expected_output["Backplane"] = {
            "Slot1 HSBP2 Temp": Temperature("Slot1_BHS2U8X4EDSFF_HSBP_2-Slot1 HSBP2", 25.312),
            "Slot1 HSBP1 Temp": Temperature("Slot1_BHS2U8X4U2_HSBP_1-Slot1 HSBP1", 23.562),
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
            "Fans": Power("Fans", 3.48 + 2.58),
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

    bmc = IntelBMC(pathlib.Path(""), None)
    with patch.object(IntelBMC, "get_redfish_url", side_effect=get):
        assert bmc._get_psu_input_sensors()
        assert not bmc._get_gpu_sensors()
        assert bmc._get_temperature_sensors()
        assert bmc._get_fan_sensors()
        assert bmc._get_fans_power_sensors()
    sensors = [url for url in REDFISH_TREE if "/Sensors/" in url]
    assert {url: requests[url] for url in sensors} == dict.fromkeys(sensors, 1)


def test_bmc_not_answering():
    """A sensor or a sensors collection the BMC does not answer for is skipped, not fatal."""
    tree = dict(REDFISH_TREE)
    tree["/redfish/v1/Chassis/R4000_Chassis/Sensors/fantach_Fan_1"] = None
    tree["/redfish/v1/Chassis/Intel_Front_Panel/Sensors"] = None
    metrics = avenue_city_metrics(tree=tree)
    assert "Fan 1" not in metrics.Fans.Fan
    assert "Fan 2" in metrics.Fans.Fan
    assert "Front Panel Temp" not in metrics.Thermal["SystemBoard"]
    assert "BMC Temp" in metrics.Thermal["SystemBoard"]


def iteration_requests(read: Callable[[BMC], object]) -> collections.Counter:
    """Return the urls <read> requests from the Intel BMC on an iteration, once the sensors detected."""
    vendor = intel_vendor(pathlib.Path(""))
    bmc = vendor.get_bmc()
    requests: collections.Counter = collections.Counter()

    def get(url, *_):
        requests[url] += 1
        return REDFISH_TREE.get(url)

    with patch.object(IntelBMC, "get_redfish_url", side_effect=get):
        bmc.read_metrics(MonitoringContexts())
        requests.clear()
        read(bmc)
    return requests


def test_thermals_requests():
    """An iteration only reads the 30 temperature sensors hwbench reports, not the 54 the BMC exposes."""
    requests = iteration_requests(lambda bmc: bmc.read_thermals(MonitoringContexts().Thermal))
    sensors = [url for url in requests if "/Sensors/" in url]
    assert len(sensors) == 30
    assert all(count == 1 for count in requests.values())
    assert not [url for url in requests if url.endswith("/Sensors")]


def test_fans_requests():
    """An iteration only reads the 16 fan speed sensors, not the 32 sensors whose url names a fan."""
    requests = iteration_requests(lambda bmc: bmc.read_fans(MonitoringContexts().Fans))
    assert len([url for url in requests if "/Sensors/" in url]) == 16
    assert all(count == 1 for count in requests.values())
    assert not [url for url in requests if url.endswith("/Sensors")]


def test_iteration_requests():
    """An iteration only reads the sensors hwbench reports, each once, and the Power resource of the baseboard."""
    requests = iteration_requests(lambda bmc: bmc.read_metrics(MonitoringContexts()))
    powers = [url for url in requests if url.endswith("/Power")]
    assert powers == ["/redfish/v1/Chassis/AVC_Baseboard/Power"]
    # 30 temperatures, 16 fans, 2 power supplies and 2 fan boards
    assert len([url for url in requests if "/Sensors/" in url]) == 50
    assert sum(requests.values()) <= 52


class FakeTelemetry:
    """The TelemetryService of the Avenue City BMC, as telemetry_probe.py recorded it, serving REDFISH_TREE."""

    SERVICE = "/redfish/v1/TelemetryService"
    DEFINITIONS = f"{SERVICE}/MetricReportDefinitions"
    REPORTS = f"{SERVICE}/MetricReports"

    def __init__(self, status: int = 201, definitions: list[str] | None = None):
        self.status = status
        self.definitions = {url: [] for url in definitions or []}  # type: dict[str, list[str]]
        self.deleted: list[str] = []
        self.requests: collections.Counter = collections.Counter()

    def get(self, url, *_):
        self.requests[url] += 1
        if url == self.SERVICE:
            return {
                "MaxReports": 10,
                "MetricReportDefinitions": {"@odata.id": self.DEFINITIONS},
                "MetricReports": {"@odata.id": self.REPORTS},
                "MinCollectionInterval": "PT1.000S",
                "Status": {"State": "Enabled"},
            }
        if url == self.DEFINITIONS:
            return {"Members": [{"@odata.id": definition} for definition in self.definitions]}
        if url.startswith(f"{self.REPORTS}/"):
            sensors = self.definitions.get(f"{self.DEFINITIONS}/{url.rsplit('/', 1)[-1]}")
            if sensors is None:
                return {}
            return {
                "MetricValues": [
                    {
                        "MetricProperty": sensor,
                        # bmcweb reports a sensor without reading as nan
                        "MetricValue": "nan"
                        if REDFISH_TREE[sensor]["Reading"] is None
                        else f"{REDFISH_TREE[sensor]['Reading']:f}",
                    }
                    for sensor in sensors
                ]
            }
        return REDFISH_TREE.get(url)

    def post(self, url, body):
        if self.status == 201:
            self.definitions[f"{url}/{body['Id']}"] = [metric["MetricProperties"][0] for metric in body["Metrics"]]
        return SimpleNamespace(status=self.status, text="")

    def delete(self, url):
        self.deleted.append(url)
        self.definitions.pop(url, None)
        return SimpleNamespace(status=204, text="")


def telemetry_bmc(telemetry: FakeTelemetry, bmc_type: type[BMC] = BMC) -> BMC:
    """Return a BMC driver connected to <telemetry>, the generic one by default."""
    vendor = intel_vendor(pathlib.Path(""))
    vendor.bmc = bmc_type(pathlib.Path(""), vendor)
    vendor.bmc.redfish_obj = telemetry
    return vendor.bmc


def test_telemetry_report():
    """The monitored sensors are read from one TelemetryService report, giving the same metrics."""
    telemetry = FakeTelemetry()
    bmc = telemetry_bmc(telemetry)
    with patch.object(BMC, "get_redfish_url", side_effect=telemetry.get):
        bmc.read_metrics(MonitoringContexts())
        # The input power of the 2 power supplies
        assert bmc.start_telemetry() == 2
        telemetry.requests.clear()
        power_supplies = bmc.read_power_supplies(MonitoringContexts().PowerSupplies)
    # The report instead of the sensors
    assert telemetry.requests[f"{FakeTelemetry.REPORTS}/hwbench_{os.getpid()}"] == 1
    assert not [url for url in telemetry.requests if "/Sensors/" in url]
    assert power_supplies == avenue_city_metrics(BMC).PowerSupplies


def test_telemetry_report_cleanup():
    """The reports of hwbench a killed run left are deleted when starting, the report of the run when stopping."""
    left = [f"{FakeTelemetry.DEFINITIONS}/hwbench_1", f"{FakeTelemetry.DEFINITIONS}/other"]
    telemetry = FakeTelemetry(definitions=left)
    bmc = telemetry_bmc(telemetry)
    with patch.object(BMC, "get_redfish_url", side_effect=telemetry.get):
        bmc.start_telemetry()
        assert telemetry.deleted == [f"{FakeTelemetry.DEFINITIONS}/hwbench_1"]
        bmc.stop_telemetry()
    assert list(telemetry.definitions) == [f"{FakeTelemetry.DEFINITIONS}/other"]
    assert not bmc.telemetry_report


def test_telemetry_report_refused():
    """A BMC refusing the report has its sensors read one by one."""
    telemetry = FakeTelemetry(status=400)
    bmc = telemetry_bmc(telemetry)
    with patch.object(BMC, "get_redfish_url", side_effect=telemetry.get):
        assert bmc.start_telemetry() == 0
        metrics = bmc.read_metrics(MonitoringContexts())
    assert not bmc.telemetry_report
    assert metrics == avenue_city_metrics(BMC)


def test_telemetry_report_without_reading():
    """A sensor the report has no reading for, written nan, is skipped like one the BMC reads None for."""
    psu1 = "/redfish/v1/Chassis/AVC_Baseboard/Sensors/power_PSU1_Input_Power"
    telemetry = FakeTelemetry()
    bmc = telemetry_bmc(telemetry)
    with patch.object(BMC, "get_redfish_url", side_effect=telemetry.get):
        bmc.read_metrics(MonitoringContexts())
        bmc.start_telemetry()
        with patch.dict(REDFISH_TREE, {psu1: REDFISH_TREE[psu1] | {"Reading": None}}):
            power_supplies = bmc.read_power_supplies(MonitoringContexts().PowerSupplies)
    assert list(power_supplies.BMC) == ["PSU2"]


def test_telemetry_report_avenue_city():
    """All the sensors the Intel driver monitors are read from the report, giving the same metrics."""
    telemetry = FakeTelemetry()
    bmc = telemetry_bmc(telemetry, IntelBMC)
    with patch.object(IntelBMC, "get_redfish_url", side_effect=telemetry.get):
        bmc.read_metrics(MonitoringContexts())
        # 30 temperatures, 16 fans, 2 power supplies and 2 fan boards
        assert bmc.start_telemetry() == 50
        telemetry.requests.clear()
        metrics = bmc.read_metrics(MonitoringContexts())
    report = f"{FakeTelemetry.REPORTS}/hwbench_{os.getpid()}"
    assert set(telemetry.requests) == {report, "/redfish/v1/Chassis/AVC_Baseboard/Power"}
    assert metrics == avenue_city_metrics()


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
