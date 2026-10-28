from __future__ import annotations

import configparser

import pytest

from hwbench.environment.vendors.monitoring_device import REDACTED, redact_secrets, section_value


@pytest.fixture
def config() -> configparser.ConfigParser:
    config = configparser.ConfigParser(allow_no_value=True, interpolation=None)
    config.read_string("[default]\ntype=BMC\nusername=admin\npassword=\n[PDU_1]\ntype=PDU\npdu_id=2\n")
    return config


def test_section_value(config):
    """A key set gives its value, converted when asked; absent or empty, it gives its fallback."""
    assert section_value(config, "BMC", "default", "username") == "admin"
    assert section_value(config, "PDU", "PDU_1", "pdu_id", "1", int) == 2
    assert section_value(config, "PDU", "PDU_1", "group", "") == ""
    assert section_value(config, "BMC", "default", "url", "") == ""


@pytest.mark.parametrize(
    ("device", "section", "key", "convert", "error"),
    [
        # Without fallback, a key is required: a BMC without password stopped hwbench on a NoOptionError
        ("BMC", "default", "password", None, "BMC default: password is required"),
        ("PDU", "PDU_1", "url", None, "PDU PDU_1: url is required"),
        ("PDU", "PDU_1", "type", float, "PDU PDU_1: type must be a number, got 'PDU'"),
    ],
)
def test_section_value_errors(config, caplog, device, section, key, convert, error):
    with pytest.raises(SystemExit):
        section_value(config, device, section, key, convert=convert)
    assert error in caplog.text


def test_redact_secrets():
    """The secrets are redacted, not their absence nor the flags telling whether one is used."""
    attributes = {
        "Users.2.UserName": "root",
        "Users.2.SHA256Password": "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",
        "Users.2.SHA256PasswordSalt": "FEDCBA9876543210FEDCBA9876543210",
        "Users.2.IPMIKey": "00112233445566778899AABBCCDDEEFF",
        "Users.2.Password": None,
        "Users.3.SHA256Password": "",
        "Users.2.EnableSNMPv3Passphrase": "Disabled",
        "SNMP.1.AgentCommunity": "public",
        "SHA256SetupPassword": "0123456789ABCDEF",
        "StrongPassword": "Enabled",
        "ProcCores": 32,
    }
    redacted = redact_secrets({"Attributes": attributes, "Members": [{"Password": "secret"}]})
    assert redacted["Attributes"] == attributes | {
        "Users.2.SHA256Password": REDACTED,
        "Users.2.SHA256PasswordSalt": REDACTED,
        "Users.2.IPMIKey": REDACTED,
        "SNMP.1.AgentCommunity": REDACTED,
        "SHA256SetupPassword": REDACTED,
    }
    assert redacted["Members"] == [{"Password": REDACTED}]
