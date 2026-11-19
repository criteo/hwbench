import ast
import pathlib

from redfish_dump import Anonymizer, anonymize, dump_fixtures, format_fixture

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment import test_bmc_gpu, test_vendors
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


def test_dump_bios_and_bmc_config():
    """The BIOS and BMC configurations hwbench saves are recorded too."""
    avenue_city = test_vendors.vendors_tree("Intel/AvenueCity")
    _, _, fixtures = served_bmc(avenue_city)
    configurations = {url for url in avenue_city if url.endswith("/Bios") or url.startswith("/redfish/v1/Managers")}
    assert "/redfish/v1/Managers/bmc/NetworkProtocol" in configurations
    assert configurations <= set(fixtures["redfish_tree"])


TELEMETRY = "/redfish/v1/TelemetryService"
SERVICES_TREE = {
    "/redfish/v1": {
        "TelemetryService": {"@odata.id": TELEMETRY},
        "LicenseService": {"@odata.id": "/redfish/v1/LicenseService"},
    },
    TELEMETRY: {
        "MetricReportDefinitions": {"@odata.id": f"{TELEMETRY}/MetricReportDefinitions"},
        "MetricDefinitions": {"@odata.id": f"{TELEMETRY}/MetricDefinitions"},
    },
    f"{TELEMETRY}/MetricReportDefinitions": {
        "Members": [{"@odata.id": f"{TELEMETRY}/MetricReportDefinitions/PowerMetrics"}]
    },
    f"{TELEMETRY}/MetricReportDefinitions/PowerMetrics": {"MetricReportDefinitionType": "Periodic"},
    f"{TELEMETRY}/MetricDefinitions": {"Members": [{"@odata.id": f"{TELEMETRY}/MetricDefinitions/SystemInputPower"}]},
    "/redfish/v1/LicenseService": {"Licenses": {"@odata.id": "/redfish/v1/LicenseService/Licenses"}},
    "/redfish/v1/LicenseService/Licenses": {"Members": [{"@odata.id": "/redfish/v1/LicenseService/Licenses/1"}]},
    "/redfish/v1/LicenseService/Licenses/1": {"EntitlementId": "ABCD1234EFGH", "Name": "iDRAC9 Datacenter License"},
}


def test_dump_services():
    """The TelemetryService and the LicenseService the service root links to are recorded with their
    collections, the members of the MetricDefinitions being only listed."""
    _, _, fixtures = served_bmc(MANAGERS | SERVICES_TREE)
    tree = fixtures["redfish_tree"]
    assert set(SERVICES_TREE) <= set(tree)
    assert f"{TELEMETRY}/MetricDefinitions/SystemInputPower" not in tree
    anonymized, _ = anonymize(fixtures)
    assert anonymized["redfish_tree"]["/redfish/v1/LicenseService/Licenses/1"]["EntitlementId"] == "SERIAL1"


def test_dump_without_services():
    """A BMC whose service root links no TelemetryService, like an iLO 6, gets only its service root read."""
    _, _, fixtures = served_bmc(MANAGERS | {"/redfish/v1": {"Managers": {"@odata.id": "/redfish/v1/Managers/"}}})
    assert not [url for url in fixtures["redfish_tree"] if "Telemetry" in url or "License" in url]


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


def test_uuids_under_any_key():
    """An UUID is replaced whatever its key and its case, like the SMBIOS UUID a Dell repeats in its BIOS."""
    tree = {
        "/redfish/v1/Systems/System.Embedded.1": {
            "UUID": "4c4c4544-0041-4210-8043-b1c04f123456",
            "Oem": {"Dell": {"DellSystem": {"smbiosGUID": "44454c4c-4100-1042-8043-b1c04f123456"}}},
            "TrustedModules": [{"UUID": "00000000-0000-0000-0000-000000000000"}],
        },
        "/redfish/v1/Systems/System.Embedded.1/Bios": {
            "Attributes": {"NvmeofHostId": "4C4C4544-0041-4210-8043-B1C04F123456"},
        },
    }
    anonymized, anonymizer = anonymize({"redfish_tree": tree})
    out = anonymized["redfish_tree"]

    system = out["/redfish/v1/Systems/System.Embedded.1"]
    assert system["UUID"] == "00000000-0000-0000-0000-000000000001"
    assert system["Oem"]["Dell"]["DellSystem"]["smbiosGUID"] == "00000000-0000-0000-0000-000000000002"
    # The null UUID identifies nothing
    assert system["TrustedModules"] == [{"UUID": "00000000-0000-0000-0000-000000000000"}]
    bios = out["/redfish/v1/Systems/System.Embedded.1/Bios"]
    assert bios["Attributes"]["NvmeofHostId"] == "00000000-0000-0000-0000-000000000001"
    assert "4c4c4544" not in repr(out).lower()


def test_other_serial_numbers():
    """The Dell express service code and the PPIN of a processor identify the machine like its serial number."""
    tree = {
        "/redfish/v1/Systems/System.Embedded.1": {
            "Oem": {"Dell": {"DellSystem": {"ChassisServiceTag": "AB12CD3", "ExpressServiceCode": "22715473671"}}},
        },
        "/redfish/v1/Systems/System.Embedded.1/Processors?$expand=.": {
            "Members": [{"ProcessorId": {"ProtectedIdentificationNumber": "0123456789ABCDEF"}}],
        },
    }
    anonymized, _ = anonymize({"redfish_tree": tree})
    out = anonymized["redfish_tree"]

    dell = out["/redfish/v1/Systems/System.Embedded.1"]["Oem"]["Dell"]["DellSystem"]
    assert dell == {"ChassisServiceTag": "SERIAL1", "ExpressServiceCode": "SERIAL2"}
    (processor,) = out["/redfish/v1/Systems/System.Embedded.1/Processors?$expand=."]["Members"]
    assert processor["ProcessorId"]["ProtectedIdentificationNumber"] == "SERIAL3"


def test_ip_addresses_in_urls():
    """The IP address of an url is replaced, not a public host name."""
    tree = {
        "/redfish/v1/Managers/iDRAC.Embedded.1": {
            "Oem": {"Dell": {"DelliDRACCard": {"URLString": "https://10.1.2.3:443"}}},
            "Links": {"Self": "http://[2001:db8:1::5]/redfish/v1"},
            "Description": "See https://redfish.dmtf.org/schemas/v1/Manager.json",
        },
    }
    anonymized, _ = anonymize({"redfish_tree": tree})
    manager = anonymized["redfish_tree"]["/redfish/v1/Managers/iDRAC.Embedded.1"]
    assert manager["Oem"]["Dell"]["DelliDRACCard"]["URLString"] == "https://192.0.2.1:443"
    assert manager["Links"]["Self"] == "http://[2001:db8::1]/redfish/v1"
    assert manager["Description"] == "See https://redfish.dmtf.org/schemas/v1/Manager.json"


def test_secrets_are_redacted():
    tree = {"/redfish/v1/Managers/1/Attributes": {"Attributes": {"Users.2.SHA256Password": "0123ABCD"}}}
    anonymized, _ = anonymize({"redfish_tree": tree})
    attributes = anonymized["redfish_tree"]["/redfish/v1/Managers/1/Attributes"]["Attributes"]
    assert attributes == {"Users.2.SHA256Password": "<redacted>"}


def test_flags_and_default_accounts_are_neutral():
    """A flag or a default account under an identifying key is not replaced everywhere."""
    attributes = {
        "Autodiscovery.1.EnableIPChangeAnnounceFrommDNS": "Enabled",
        "IPv4.1.DHCPEnable": "Enabled",
        "Users.2.UserName": "Administrator",
        "Users.2.IpmiLanPrivilege": "Administrator",
        "DelegatedAuth.1.ServiceEnabled": "Disabled",
    }
    anonymized, _ = anonymize({"redfish_tree": {"/redfish/v1/Managers/1/Attributes": {"Attributes": attributes}}})
    assert anonymized["redfish_tree"]["/redfish/v1/Managers/1/Attributes"]["Attributes"] == attributes


def test_engine_id_and_certificate_names():
    """The SNMP engine ID and the common names of the certificates of an iDRAC identify it."""
    attributes = {
        "SNMP.1.EngineID": "0x80001f8804414231324344",
        "SecurityCertificate.1.IssuerCommonName": "0AB123-0123-4CDE-567F",
        "SecurityCertificate.1.IssuerOrganization": "Wistron",
    }
    anonymized, _ = anonymize({"redfish_tree": {"/redfish/v1/Managers/1/Attributes": {"Attributes": attributes}}})
    assert anonymized["redfish_tree"]["/redfish/v1/Managers/1/Attributes"]["Attributes"] == {
        "SNMP.1.EngineID": "SERIAL1",
        "SecurityCertificate.1.IssuerCommonName": "SERIAL2",
        "SecurityCertificate.1.IssuerOrganization": "Wistron",
    }


def test_short_values_are_only_replaced_in_place():
    out = Anonymizer()
    out.collect({"HostName": "n1", "Name": "n1 sensor"})
    out.compile()
    assert out.replace({"HostName": "n1", "Name": "n1 sensor"}) == {"HostName": "host1", "Name": "n1 sensor"}
