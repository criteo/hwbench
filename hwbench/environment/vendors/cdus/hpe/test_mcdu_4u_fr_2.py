from __future__ import annotations

import configparser
import json
from types import SimpleNamespace

import pytest
from snmp.smi import Integer32, VarBind, VarBindList

from hwbench.environment.vendors.cdus import init as init_cdu
from hwbench.environment.vendors.cdus.snmp import SNMPv2cCDU

from .mcdu_4u_fr_2 import HPEMCDU4UFR2, METRICS


def test_hpe_profile_identity_and_readings(monkeypatch):
    config = configparser.ConfigParser()
    config.read_dict(
        {
            "cooling": {
                "vendor": "HPE",
                "model": "MCDU-4U-FR-2",
                "protocol": "SNMP_V2C",
                "host": "cdu.example",
                "community": "test-community",
            }
        }
    )

    def query(self):
        assert self.metrics == METRICS
        return VarBindList(*(VarBind(spec.oid, Integer32(123)) for spec in self.metrics.values()))

    monkeypatch.setattr(SNMPv2cCDU, "_query", query)
    cdu = init_cdu(SimpleNamespace(monitoring_config_file=config), "cooling")
    assert isinstance(cdu, HPEMCDU4UFR2)
    assert cdu.dump()["vendor"] == "HPE"
    assert cdu.dump()["model"] == "MCDU-4U-FR-2"
    assert cdu.dump()["protocol"] == "SNMP_V2C"
    assert "test-community" not in json.dumps(cdu.dump())
    assert len(cdu.get_metrics()) == 16
    sample = cdu.sample()
    assert sample.errors == {}
    assert sample.values["primary_supply_temperature"] == pytest.approx(12.3)
    assert sample.values["secondary_flow"] == pytest.approx(12.3)
    assert sample.values["humidity"] == pytest.approx(12.3)
    assert sample.values["pump1_rpm"] == 123
    assert sample.values["primary_supply_pressure"] == 123
    assert cdu.get_metrics()["primary_supply_pressure"].unit == "raw"


@pytest.mark.parametrize("model", ["MCDU-4U-F-R2", "MCDU-4U-RR-2", "unknown"])
def test_hpe_profile_requires_exact_model_name(model):
    config = configparser.ConfigParser()
    config.read_dict({"cooling": {"vendor": "HPE", "model": model}})
    with pytest.raises(SystemExit):
        init_cdu(SimpleNamespace(monitoring_config_file=config), "cooling")


def test_hpe_model_rejects_globally_known_but_unsupported_protocol(caplog):
    config = configparser.ConfigParser()
    config.read_dict(
        {
            "cooling": {
                "vendor": "HPE",
                "model": "MCDU-4U-FR-2",
                "host": "cdu.example",
                "protocol": "SNMP_V3",
            },
        }
    )
    with pytest.raises(SystemExit):
        init_cdu(SimpleNamespace(monitoring_config_file=config), "cooling")
    assert "this model does not support SNMP_V3; supported protocols: SNMP_V2C" in caplog.text
    assert "community" not in caplog.text
