from __future__ import annotations

import configparser
import dataclasses
import json
import socket
from types import SimpleNamespace

import pytest
from snmp import ErrorResponse, ImproperResponse, Timeout
from snmp.pdu import ErrorStatus, GetRequestPDU
from snmp.smi import Integer32, NoSuchInstance, VarBind, VarBindList

from hwbench.bench.cdu_monitoring import CDUMonitoring
from hwbench.bench.monitoring_structs import CDUMetric
from hwbench.environment.vendors.cdus import VENDORS
from hwbench.environment.vendors.cdus import init as init_cdu
from hwbench.environment.vendors.cdus.snmp import SNMPv2cCDU
from hwbench.environment.vendors.mock import MockVendor
from hwbench.environment.vendors.vendor import Vendor

METRICS = {
    "primary_supply_temperature": CDUMetric("Supply temperature", "1.3.6.1.4.1.99999.1.0", "Celsius", 0.1),
    "humidity": CDUMetric("Humidity", "1.3.6.1.4.1.99999.2.0", "Percent", 0.1),
    "pump1_rpm": CDUMetric("Pump speed", "1.3.6.1.4.1.99999.3.0", "RPM"),
    "primary_supply_pressure": CDUMetric("Pressure reading", "1.3.6.1.4.1.99999.4.0", "raw"),
}


class ExampleCDU(SNMPv2cCDU):
    def __init__(self, vendor, section):
        super().__init__(vendor, section, "EXAMPLE", "different-cdu", METRICS)


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.setitem(VENDORS, "EXAMPLE", {"different-cdu": ExampleCDU})
    config = configparser.ConfigParser()
    config.read_dict(
        {
            "cooling": {
                "host": "cdu.example",
                "vendor": "EXAMPLE",
                "model": "different-cdu",
                "protocol": "SNMP_V2C",
                "community": "test-read-secret",
            }
        }
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP, "", ("127.0.0.1", port)),
        ],
    )
    return SimpleNamespace(monitoring_config_file=config)


def response(values=None, metrics=METRICS):
    if values is None:
        values = {key: 123 for key in metrics}
    return VarBindList(
        *(
            VarBind(metrics[key].oid, Integer32(value) if isinstance(value, int) else value)
            for key, value in values.items()
        )
    )


def test_batched_get_conversion_and_secret_isolation(vendor, monkeypatch):
    from snmp import SNMPv2c, UDP_IPv4

    closed = []

    class FakeEngine:
        def __init__(self, version):
            assert version == SNMPv2c

        def Manager(self, address, *, domain, community):
            assert address == ("127.0.0.1", 161)
            assert domain == UDP_IPv4
            assert community == b"test-read-secret"
            return SimpleNamespace(get=self.get)

        @staticmethod
        def get(*oids, **kwargs):
            assert oids == tuple(spec.oid for spec in METRICS.values())
            assert kwargs == {"timeout": 0.5, "refreshPeriod": 1.5, "wait": True}
            return response()

        def __del__(self):
            closed.append(True)

    monkeypatch.setattr("hwbench.environment.vendors.cdus.snmp.Engine", FakeEngine)
    cdu = init_cdu(vendor, "cooling")
    sample = cdu.sample()
    assert closed == [True]
    assert sample.errors == {}
    assert sample.values["primary_supply_temperature"] == pytest.approx(12.3)
    assert sample.values["humidity"] == pytest.approx(12.3)
    assert sample.values["pump1_rpm"] == 123
    assert sample.values["primary_supply_pressure"] == 123
    assert "test-read-secret" not in json.dumps(cdu.dump())
    assert cdu.dump()["model"] == "different-cdu"
    assert cdu.dump()["vendor"] == "EXAMPLE"
    assert cdu.dump()["type"] == "CDU"
    assert cdu.dump()["protocol"] == "SNMP_V2C"


def test_partial_response_preserves_zero_but_not_missing_values(vendor, monkeypatch):
    def query(self):
        raise ImproperResponse(
            response(
                {
                    "primary_supply_temperature": 0,
                    "pump1_rpm": 4500,
                    "humidity": NoSuchInstance(),
                }
            )
        )

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    sample = init_cdu(vendor, "cooling").sample()
    assert sample.values["primary_supply_temperature"] == 0
    assert sample.values["pump1_rpm"] == 4500
    assert sample.values["humidity"] is None
    assert sample.errors["humidity"] == "missing_or_invalid_oid"
    assert len(sample.values) == 4
    assert len(sample.errors) == 2
    assert '"humidity": null' in json.dumps(dataclasses.asdict(sample), allow_nan=False)


@pytest.mark.parametrize("reason", ["timeout", "transport_error", "snmp_error"])
def test_failed_request_marks_every_reading_missing(vendor, monkeypatch, reason):
    def query(self):
        if reason == "timeout":
            raise Timeout()
        if reason == "transport_error":
            raise OSError("sensitive error that must not be logged")
        raise ErrorResponse(ErrorStatus.genErr, 0, GetRequestPDU(*(spec.oid for spec in METRICS.values())))

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    sample = init_cdu(vendor, "cooling").sample()
    assert all(value is None for value in sample.values.values())
    assert set(sample.errors.values()) == {reason}


def test_no_stale_readings_after_recovery(vendor, monkeypatch):
    responses = iter([response(), Timeout(), response({"pump1_rpm": 4400})])

    def query(self):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    cdu = init_cdu(vendor, "cooling")
    assert cdu.sample().values["pump1_rpm"] == 123
    assert cdu.sample().values["pump1_rpm"] is None
    recovered = cdu.sample()
    assert recovered.values["pump1_rpm"] == 4400
    assert recovered.values["humidity"] is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("host", ""),
        ("port", "0"),
        ("timeout", "0"),
        ("timeout", "inf"),
        ("timeout", "nan"),
        ("timeout", "-1"),
        # Beyond half the monitoring precision, a CDU not answering would delay the monitoring loop
        ("timeout", "1.1"),
        ("community", ""),
    ],
)
def test_reject_invalid_configuration(vendor, key, value):
    vendor.monitoring_config_file.set("cooling", key, value)
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")


def test_direct_community_is_not_interpolated(vendor):
    config = vendor.monitoring_config_file
    config.set("cooling", "community", "read%%community")
    assert init_cdu(vendor, "cooling").community == "read%%community"


def test_community_is_no_longer_limited_by_net_snmp_configuration_syntax(vendor):
    config = vendor.monitoring_config_file
    community = 'read # with spaces, "quotes" and \\backslashes'
    config.set("cooling", "community", community)
    assert init_cdu(vendor, "cooling").community == community


def test_dns_failure_is_a_transport_error(vendor, monkeypatch):
    def resolve(*args, **kwargs):
        raise OSError("DNS failure")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    sample = init_cdu(vendor, "cooling").sample()
    assert set(sample.errors.values()) == {"transport_error"}
    assert all(value is None for value in sample.values.values())


def test_prepare_loads_cdus_without_redfish_and_only_once(tmp_path, vendor):
    config = tmp_path / "monitoring.cfg"
    config.write_text(
        "[cooling]\ntype=CDU\nvendor=EXAMPLE\nmodel=different-cdu\nprotocol=SNMP_V2C\nhost=cdu.example\ncommunity=test-read-secret\n"
    )
    vendor = MockVendor(tmp_path, None, str(config))
    Vendor.prepare(vendor)
    Vendor.prepare(vendor)
    assert len(vendor.get_cdus()) == 1
    assert vendor.get_pdus() == []
    assert vendor.get_cdus()[0].get_name() == "cooling"
    assert "community" not in json.dumps(vendor.get_cdus()[0].dump())


def test_missing_community(vendor):
    vendor.monitoring_config_file.remove_option("cooling", "community")
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")


@pytest.mark.parametrize(
    ("key", "value"), [("vendor", ""), ("vendor", "unknown"), ("model", ""), ("model", "other-model")]
)
def test_vendor_and_model_are_required_and_never_fall_back(vendor, key, value):
    vendor.monitoring_config_file.set("cooling", key, value)
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")


def test_two_models_of_one_vendor_use_distinct_oids(vendor, monkeypatch):
    other_oid = "1.3.6.1.4.1.99999.100.0"

    class OtherExampleCDU(SNMPv2cCDU):
        def __init__(self, vendor, section):
            super().__init__(
                vendor,
                section,
                "EXAMPLE",
                "test-model",
                {
                    "different_sensor": CDUMetric("Other sensor", other_oid, "Celsius", 0.01),
                },
            )

    monkeypatch.setitem(VENDORS["EXAMPLE"], "test-model", OtherExampleCDU)
    first = init_cdu(vendor, "cooling")
    vendor.monitoring_config_file.set("cooling", "model", "test-model")
    second = init_cdu(vendor, "cooling")
    assert first.get_model() == "different-cdu"
    assert second.get_model() == "test-model"
    assert first.get_metrics() == METRICS
    assert set(second.get_metrics()) == {"different_sensor"}

    def query(self):
        assert [spec.oid for spec in self.metrics.values()] == [other_oid]
        return response({"different_sensor": 2300}, self.metrics)

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    assert second.sample().values == {"different_sensor": 23.0}


@pytest.mark.parametrize("protocol", ["", "SNMP", "snmp_v2c", "unknown"])
def test_protocol_is_required_and_must_be_explicit(vendor, protocol, caplog):
    vendor.monitoring_config_file.set("cooling", "protocol", protocol)
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")
    assert "protocol must be explicitly set" in caplog.text


def test_unknown_protocol_is_rejected_before_credentials_or_network(vendor, monkeypatch, caplog):
    config = vendor.monitoring_config_file
    config.set("cooling", "protocol", "UNKNOWN")
    config.remove_option("cooling", "community")

    def resolve(*args, **kwargs):
        pytest.fail("Unsupported protocol must not send a request")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")
    assert "protocol must be explicitly set" in caplog.text
    assert "community" not in caplog.text


def test_other_vendor_uses_own_metrics_with_shared_transport_and_polling(vendor, monkeypatch):
    oid = "1.3.6.1.4.1.99999.7.0"

    class OtherVendorModel(SNMPv2cCDU):
        def __init__(self, vendor, section):
            super().__init__(
                vendor,
                section,
                "OTHER",
                "different-cdu",
                {
                    "conductivity": CDUMetric("Coolant conductivity", oid, "uS/cm", 0.01),
                },
            )

    monkeypatch.setitem(VENDORS, "OTHER", {"different-cdu": OtherVendorModel})
    config = vendor.monitoring_config_file
    config.set("cooling", "vendor", "OTHER")
    config.set("cooling", "model", "different-cdu")
    config.set("cooling", "port", "1161")
    cdu = init_cdu(vendor, "cooling")

    def query(self):
        assert self.port == 1161
        assert [spec.oid for spec in self.metrics.values()] == [oid]
        return response({"conductivity": 2350}, self.metrics)

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    monitoring = CDUMonitoring([cdu])
    monitoring.poll()
    monitoring.compact()
    data = monitoring.data["cooling"]
    assert data.readings["conductivity"].mean == [23.5]
    assert data.readings["conductivity"].errors == [{}]
    assert data.metrics["conductivity"].unit == "uS/cm"
    assert cdu.dump()["vendor"] == "OTHER"


def test_recognized_protocol_must_be_supported_by_selected_model(vendor, monkeypatch, caplog):
    config = vendor.monitoring_config_file
    config.set("cooling", "protocol", "SNMP_V3")
    config.remove_option("cooling", "community")

    def resolve(*args, **kwargs):
        pytest.fail("Unsupported model protocol must not send a request")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(SystemExit):
        init_cdu(vendor, "cooling")
    assert "this model does not support SNMP_V3; supported protocols: SNMP_V2C" in caplog.text
    assert "community" not in caplog.text


@pytest.mark.parametrize(
    ("host", "endpoint"),
    [
        ("cdu.example", "snmp://cdu.example:1161"),
        ("127.0.0.1", "snmp://127.0.0.1:1161"),
        ("::1", "snmp://[::1]:1161"),
        ("2001:db8::1", "snmp://[2001:db8::1]:1161"),
    ],
)
def test_endpoint_formats_ipv6_without_changing_request_host(vendor, host, endpoint):
    config = vendor.monitoring_config_file
    config.set("cooling", "host", host)
    config.set("cooling", "port", "1161")
    cdu = init_cdu(vendor, "cooling")
    assert cdu.get_url() == endpoint
    assert cdu.host == host
