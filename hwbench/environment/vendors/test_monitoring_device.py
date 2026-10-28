from __future__ import annotations

import configparser
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
import redfish  # type: ignore

from hwbench.environment.vendors.monitoring_device import (
    REDACTED,
    DeviceError,
    DeviceNotReady,
    RedfishDevice,
    init_timeout,
    redact_secrets,
    retry_delays,
    section_value,
)


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
    device = RedfishDevice(None)
    device.redfish_obj = mock.Mock()
    device.redfish_obj.get.side_effect = error
    assert device.get_redfish_url("/redfish/v1/Chassis/1/Thermal") == {}


def test_get_redfish_url_timeout(caplog):
    """A request not answered in time is counted and reported with its url."""
    device = RedfishDevice(None)
    device.redfish_url = "https://bmc"
    device.redfish_obj = mock.Mock()
    device.redfish_obj.get.side_effect = redfish.rest.v1.RetriesExhaustedError()
    device.get_redfish_url("/redfish/v1/Chassis/1/Thermal")
    device.get_redfish_url("/redfish/v1/Chassis/1/Power")
    assert device.timeouts == 2
    assert device.did_not_answer("/redfish/v1/Chassis/1/Power")
    # The next answer of the url clears it
    device.redfish_obj.get.side_effect = None
    device.redfish_obj.get.return_value.dict = {"Id": "Power"}
    get_redfish_url_uncached = RedfishDevice.get_redfish_url.__wrapped__  # type: ignore[attr-defined]
    assert get_redfish_url_uncached(device, "/redfish/v1/Chassis/1/Power") == {"Id": "Power"}
    assert not device.did_not_answer("/redfish/v1/Chassis/1/Power")
    assert "Redfish https://bmc/redfish/v1/Chassis/1/Power did not answer in time" in caplog.text


@pytest.mark.parametrize(
    ("error", "kind", "message"),
    [
        (redfish.rest.v1.RetriesExhaustedError(), DeviceNotReady, "RetriesExhaustedError on https://bmc"),
        (
            redfish.rest.v1.ServerDownOrUnreachableError("down"),
            DeviceNotReady,
            "connecting redfish to https://bmc: down",
        ),
        (redfish.rest.v1.InvalidCredentialsError(), DeviceError, "Invalid credentials for https://bmc"),
        (redfish.rest.v1.BadRequestError(), DeviceError, "BadRequestError on https://bmc"),
    ],
    ids=["timeout", "unreachable", "credentials", "bad request"],
)
def test_connect_redfish_failure(error, kind, message):
    """A device not answering may answer a later attempt; wrong credentials never will, and retrying them
    could lock the account."""
    device = RedfishDevice(None)
    with mock.patch("redfish.redfish_client") as client:
        client.return_value.login.side_effect = error
        with pytest.raises(DeviceError) as raised:
            device._connect_redfish("admin", "admin", "https://bmc", "session")
    assert message in str(raised.value)
    assert type(raised.value) is kind


class RedfishService(BaseHTTPRequestHandler):
    """A Redfish service answering at once, its sessions included."""

    def answer(self, status: int, content: dict, headers: dict[str, str] | None = None):
        body = json.dumps(content).encode()
        self.send_response(status)
        for header, value in {"Content-Type": "application/json", **(headers or {})}.items():
            self.send_header(header, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        sessions = {"@odata.id": "/redfish/v1/SessionService/Sessions"}
        self.answer(200, {"@odata.id": self.path, "Links": {"Sessions": sessions}})

    def do_POST(self):
        self.answer(201, {}, {"X-Auth-Token": "token", "Location": "/redfish/v1/SessionService/Sessions/1"})

    def do_DELETE(self):
        self.answer(204, {})

    def log_message(self, *args):
        pass


@pytest.fixture
def redfish_service():
    """The url of a RedfishService, which the https url of the devices reaches."""
    server = HTTPServer(("127.0.0.1", 0), RedfishService)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = redfish.redfish_client

    def local_client(base_url, **kwargs):
        return client(base_url=f"http://127.0.0.1:{server.server_port}", **kwargs)

    with mock.patch("redfish.redfish_client", local_client):
        yield
    server.shutdown()


def test_connect_redfish_answered(redfish_service):
    """The requests answered give their content: with a max_retry of 0, python-redfish-library raised
    RetriesExhaustedError on all of them, the login included."""
    device = RedfishDevice(None)
    device._connect_redfish("admin", "admin", "https://bmc", redfish.AuthMethod.SESSION)
    assert device.logged
    assert device.get_redfish_url("/redfish/v1/Chassis")["@odata.id"] == "/redfish/v1/Chassis"
    assert device.timeouts == 0
    # Logged out while the service answers
    device.redfish_obj.logout()
    device.logged = False


def test_get_redfish_url_single_attempt():
    """A request not answered gives up after its timeout, not after 10 more attempts: made once, it gives
    no response."""
    device = RedfishDevice(None)
    device.redfish_obj = mock.Mock()
    device.redfish_obj.get.return_value = None
    assert device.get_redfish_url("/redfish/v1/Chassis/1/Power") == {}
    assert device.redfish_obj.get.call_args.kwargs["max_retry"] == 0
    assert device.timeouts == 1


def environment(text: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser(allow_no_value=True, interpolation=None)
    config.read_string(text)
    return config


def test_retry_settings_default():
    """Without [monitoring], the devices have 2 minutes to be ready, tried again every 5 to 30 seconds."""
    config = environment("[pdu]\ntype=PDU\n")
    assert init_timeout(config) == 120
    assert retry_delays(config, "PDU", "pdu") == list(range(5, 31))


def test_retry_delays_inherited():
    """The retry_delay of [monitoring] applies to every device, unless its section gives another one."""
    config = environment("[monitoring]\ninit_timeout=300\nretry_delay=10\n[pdu]\ntype=PDU\n[cdu]\nretry_delay=20-25\n")
    assert init_timeout(config) == 300
    assert retry_delays(config, "PDU", "pdu") == [10]
    assert retry_delays(config, "CDU", "cdu") == [20, 21, 22, 23, 24, 25]
    # A BMC without section, its credentials being missing, takes the ones of [monitoring]
    assert retry_delays(config, "BMC", None) == [10]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (
            "[monitoring]\ninit_timeout=2m\n",
            "monitoring: init_timeout must be a number of seconds, 0 or more, got '2m'",
        ),
        (
            "[monitoring]\ninit_timeout=-1\n",
            "monitoring: init_timeout must be a number of seconds, 0 or more, got '-1'",
        ),
        (
            "[monitoring]\nretry_delay=1.5\n",
            "monitoring: retry_delay must be a number of seconds, or a range of them like 5-30, got '1.5'",
        ),
        (
            "[pdu]\nretry_delay=5-10 20\n",
            "PDU pdu: retry_delay must be a number of seconds, or a range of them like 5-30, got '5-10 20'",
        ),
    ],
)
def test_retry_settings_errors(caplog, text, error):
    config = environment(text)

    def read_settings():
        init_timeout(config)
        retry_delays(config, "PDU", "pdu")

    with pytest.raises(SystemExit):
        read_settings()
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
