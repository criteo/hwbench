import ast
import pathlib

from redfish_dump import Anonymizer, anonymize, dump_fixtures, format_fixture

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment import test_bmc_gpu
from hwbench.environment.vendors.bmc import BMC

MANAGERS = {
    "/redfish/v1/Managers/": {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]},
    "/redfish/v1/Managers/1": {"FirmwareVersion": "1.2.3.4", "Model": "BMC"},
}


def served_bmc(tree: dict) -> tuple[BMC, MonitoringContexts, dict]:
    """Return a BMC serving <tree>, the metrics it reads, and its fixtures."""
    bmc = BMC(pathlib.Path(""), None)
    patcher, _ = test_bmc_gpu.TestBMCGpu(methodName="test_sensors").served(tree)
    with patcher:
        fixtures = dump_fixtures(bmc)
        contexts = bmc.read_metrics(MonitoringContexts())
    return bmc, contexts, fixtures


def gpu_server() -> dict:
    return test_bmc_gpu.TestBMCGpu(methodName="test_sensors").tree() | MANAGERS


def test_dump_replays_the_same_metrics():
    """A dumped tree must be a fixture giving the metrics read from the real BMC."""
    bmc, contexts, fixtures = served_bmc(gpu_server())

    assert bmc.get_firmware_version() == "1.2.3.4"
    assert sorted(fixtures) == ["power", "redfish_tree", "thermal"]
    tree = fixtures["redfish_tree"]
    assert set(MANAGERS) <= set(tree)
    replayed = ast.literal_eval(format_fixture(tree))
    assert replayed == tree
    _, replayed_contexts, _ = served_bmc(replayed)
    assert replayed_contexts == contexts
    assert "BMC_GPU_GPU1" in replayed_contexts.PowerConsumption.GPU


def test_anonymized_dump_replays_the_same_metrics():
    _, contexts, fixtures = served_bmc(gpu_server())
    anonymized, _ = anonymize(fixtures)
    _, replayed_contexts, _ = served_bmc(anonymized["redfish_tree"])
    assert replayed_contexts == contexts


def test_dump_extra_urls():
    bmc = BMC(pathlib.Path(""), None)
    extra = {"/redfish/v1/Chassis/1/Power/PowerMeter/": {"PowerDetail": [{"DimmWatts": 21}]}}
    patcher, _ = test_bmc_gpu.TestBMCGpu(methodName="test_sensors").served(MANAGERS | extra)
    with patcher:
        fixtures = dump_fixtures(bmc, list(extra))
    tree = fixtures["redfish_tree"]
    assert all(tree[url] == answer for url, answer in extra.items())


def test_dump_stops_recording():
    bmc, _, _ = served_bmc(MANAGERS)
    assert "get_redfish_url" not in vars(bmc)


def test_anonymize():
    tree = {
        "/redfish/v1/Chassis/AB12CD34": {
            "SerialNumber": "AB12CD34",
            "UUID": "39333550-3433-5a43-3244-324e30385638",
            "AssetTag": "Unknown",
            "FirmwareVersion": "1.2.3.4",
            "Links": {"Self": {"@odata.id": "/redfish/v1/Chassis/AB12CD34"}},
        },
        "/redfish/v1/Systems/1": {
            "HostName": "AB12CD34",
            "FQDN": "AB12CD34.bmc.corp.example",
            "Oem": {"OsSysDescription": "Linux server-42 6.1"},
            "ServerName": "server-42",
            "Boot": [
                "PciRoot(0x7)/MAC(6CFE54943750,0x1)",
                "NVMe(0x1,01-00-AA-27-B8-43-50-00)",
                "PciRoot(0x8)/MAC(000000000000,0x1)",
            ],
            "PermanentMACAddress": "00:00:00:00:00:00",
            "Attributes": {"NIC.1.MACAddress": "6C:FE:54:94:37:50", "IPv4.1.Address": "10.1.2.3", "Name": "sys"},
        },
    }
    anonymized, anonymizer = anonymize({"redfish_tree": tree})
    out = anonymized["redfish_tree"]

    chassis = out["/redfish/v1/Chassis/SERIAL1"]
    assert chassis["SerialNumber"] == "SERIAL1"
    assert chassis["Links"]["Self"]["@odata.id"] == "/redfish/v1/Chassis/SERIAL1"
    assert chassis["UUID"] == "00000000-0000-0000-0000-000000000001"
    # Neutral values, and the values of other keys, are kept
    assert chassis["AssetTag"] == "Unknown"
    assert chassis["FirmwareVersion"] == "1.2.3.4"

    system = out["/redfish/v1/Systems/1"]
    # A serial number used as hostname keeps its serial placeholder
    assert system["HostName"] == "SERIAL1"
    assert system["FQDN"] == "SERIAL1.domain1.example.com"
    assert system["Oem"]["OsSysDescription"] == "Linux host1 6.1"
    assert system["Boot"] == [
        "PciRoot(0x7)/MAC(020000000001,0x1)",
        "NVMe(0x1,02-00-00-00-00-00-00-02)",
        "PciRoot(0x8)/MAC(000000000000,0x1)",
    ]
    # A null address identifies nothing, wherever it is written
    assert system["PermanentMACAddress"] == "00:00:00:00:00:00"
    assert system["Attributes"] == {
        "NIC.1.MACAddress": "02:00:00:00:00:01",
        "IPv4.1.Address": "192.0.2.1",
        "Name": "sys",
    }
    assert not [value for value in anonymizer.placeholders.values() if value in repr(tree)]


def test_short_values_are_only_replaced_in_place():
    out = Anonymizer()
    out.collect({"HostName": "n1", "Name": "n1 sensor"})
    out.compile()
    assert out.replace({"HostName": "n1", "Name": "n1 sensor"}) == {"HostName": "host1", "Name": "n1 sensor"}
