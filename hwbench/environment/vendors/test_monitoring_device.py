from __future__ import annotations

import configparser
import json
from unittest import mock

import pytest
import redfish  # type: ignore

from hwbench.environment.vendors.monitoring_device import MonitoringDevice, section_value


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


@pytest.mark.parametrize("error", [redfish.rest.v1.RetriesExhaustedError(), json.decoder.JSONDecodeError("", "", 0)])
def test_get_redfish_url_failure(error):
    """A BMC that stops answering gives no content: the read timeout of an iLO raised an UnboundLocalError."""
    device = MonitoringDevice(None)
    device.redfish_obj = mock.Mock()
    device.redfish_obj.get.side_effect = error
    assert device.get_redfish_url("/redfish/v1/Chassis/1/Thermal") is None
