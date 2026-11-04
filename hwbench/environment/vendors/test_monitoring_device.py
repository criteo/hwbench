from __future__ import annotations

import configparser
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
import redfish  # type: ignore

from hwbench.environment.vendors.monitoring_device import DeviceError, DeviceNotReady, MonitoringDevice, section_value


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
    assert device.get_redfish_url("/redfish/v1/Chassis/1/Thermal") == {}


def test_get_redfish_url_timeout(caplog):
    """A request not answered in time is counted and reported with its url."""
    device = MonitoringDevice(None)
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
    get_redfish_url_uncached = MonitoringDevice.get_redfish_url.__wrapped__  # type: ignore[attr-defined]
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
    device = MonitoringDevice(None)
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
    device = MonitoringDevice(None)
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
    device = MonitoringDevice(None)
    device.redfish_obj = mock.Mock()
    device.redfish_obj.get.return_value = None
    assert device.get_redfish_url("/redfish/v1/Chassis/1/Power") == {}
    assert device.redfish_obj.get.call_args.kwargs["max_retry"] == 0
    assert device.timeouts == 1
