from __future__ import annotations

import asyncio
import configparser
import time
from threading import Event
from types import SimpleNamespace

import pytest

from hwbench.bench.monitoring import Monitoring, until_ready
from hwbench.bench.monitoring_structs import MonitoringContexts, MonitoringData
from hwbench.environment.vendors.mock import MockedBMC, MockVendor
from hwbench.environment.vendors.monitoring_device import DeviceError, DeviceNotReady, MonitoringDevice
from hwbench.utils import helpers as h


class ConnectedBMC(MockedBMC):
    """A BMC whose readings are mocked: connecting it reaches nothing."""

    def connect_redfish(self):
        pass


class SilentBMC(ConnectedBMC):
    """A BMC answering, without any thermal sensor yet: a BMC still booting."""

    def read_thermals(self, thermals):
        return thermals


def initialized(bmc_class):
    """A BMC of <bmc_class>, read once."""
    bmc_class(None, MockVendor(None, None)).initialize(MonitoringContexts())


def test_bmc_initialize(capsys):
    initialized(ConnectedBMC)
    assert "Monitoring/BMC: Thermal metrics: 1xCPU" in capsys.readouterr().out


def test_bmc_initialize_without_metrics():
    """A BMC giving no metric may give them to a later attempt."""
    with pytest.raises(DeviceNotReady, match="Cannot detect Thermal metrics"):
        initialized(SilentBMC)


class Device(MonitoringDevice):
    """A device answering the attempts listed in <answers>: None when ready, the exception it raises otherwise."""

    def __init__(self, label, delays, *answers):
        super().__init__()
        self.label = label
        self.delays = delays
        self.answers = list(answers)
        self.calls = 0

    def get_label(self):
        return self.label

    def get_retry_delays(self):
        return self.delays

    def initialize(self, contexts):
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if answer is not None:
            raise answer


def test_until_ready_tries_again(capsys, caplog):
    device = Device("PDU rack", [0], DeviceNotReady("timeout"), DeviceNotReady("timeout"), None)
    until_ready(device, [0], time.monotonic() + 60, Event())
    assert device.calls == 3
    assert "Monitoring/PDU rack: attempt 2 failed, trying again in 0s: timeout" in caplog.text
    assert "Monitoring/PDU rack: ready after 3 attempts" in capsys.readouterr().out


def test_until_ready_gives_up_at_the_deadline():
    """No attempt starts after the deadline: the last error is raised."""
    device = Device("PDU rack", [30], DeviceNotReady("timeout"))
    with pytest.raises(DeviceNotReady, match="^timeout, still after 1 attempts in 0s$"):
        until_ready(device, [30], time.monotonic() + 10, Event())
    assert device.calls == 1


def test_until_ready_draws_a_delay_ending_before_the_deadline(caplog):
    """A delay ending after the deadline is not drawn: a shorter one leaves room for another attempt."""
    device = Device("PDU rack", [0, 30], DeviceNotReady("timeout"), None)
    until_ready(device, [0, 30], time.monotonic() + 10, Event())
    assert device.calls == 2
    assert "trying again in 0s" in caplog.text


def test_until_ready_does_not_retry_a_device_misconfigured():
    """Wrong credentials never become right: trying them again could lock the account."""
    device = Device("BMC", [0], DeviceError("Invalid credentials for https://bmc"))
    with pytest.raises(DeviceError, match="Invalid credentials"):
        until_ready(device, [0], time.monotonic() + 60, Event())
    assert device.calls == 1


def test_until_ready_single_attempt():
    """A source of the server, like turbostat, has no delay: it is not tried again."""
    device = Device("turbostat", [], DeviceNotReady("Cannot detect Freq metrics"))
    with pytest.raises(DeviceNotReady, match="^Cannot detect Freq metrics$"):
        until_ready(device, [], time.monotonic() + 60, Event())
    assert device.calls == 1


class AsyncDevice(Device):
    """A device built on an async library: its initialize() is a coroutine."""

    def __init__(self, label, delays, *answers):
        super().__init__(label, delays, *answers)
        self.loops = []

    async def initialize(self, contexts):
        self.loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0)
        super().initialize(contexts)


def test_until_ready_async_device(capsys):
    """An async device is awaited in an event loop of its thread, the same for all its attempts."""
    device = AsyncDevice("PDU rack", [0], DeviceNotReady("timeout"), None)
    until_ready(device, [0], time.monotonic() + 60, Event())
    assert device.calls == 2
    assert len(device.loops) == 2
    assert device.loops[0] is device.loops[1]
    assert device.loops[0].is_closed()
    assert "Monitoring/PDU rack: ready after 2 attempts" in capsys.readouterr().out


def test_until_ready_async_device_misconfigured():
    device = AsyncDevice("BMC", [0], DeviceError("Invalid credentials for https://bmc"))
    with pytest.raises(DeviceError, match="Invalid credentials"):
        until_ready(device, [0], time.monotonic() + 60, Event())
    assert device.calls == 1


def test_until_ready_stops_with_the_others():
    stop = Event()
    stop.set()
    with pytest.raises(DeviceNotReady, match="attempts stopped as another device failed"):
        until_ready(Device("CDU cooling", [30], DeviceNotReady("timeout")), [30], time.monotonic() + 60, stop)


def prepare(environment, *devices):
    """Prepare a Monitoring of these <devices>, with the [monitoring] section of <environment>."""
    config = configparser.ConfigParser()
    config.read_string(environment)
    monitor = Monitoring.__new__(Monitoring)
    monitor.metrics = MonitoringData()
    monitor.vendor = SimpleNamespace(monitoring_config_file=config)
    monitor.devices = lambda: list(devices)
    monitor.prepare()


def test_prepare():
    """A PDU not answering at first is tried again, while the BMC is ready."""
    flaky = Device("PDU rack", [0], DeviceNotReady("timeout"), None)
    prepare("[monitoring]\n", Device("BMC", [0], None), flaky)
    assert flaky.calls == 2


def test_prepare_stops_on_a_device_misconfigured(caplog):
    """A device misconfigured stops the attempts of the others, without waiting for the init_timeout."""
    devices = [
        Device("BMC", [300], None),
        Device("PDU left", [0], DeviceError("Invalid credentials for https://pdu")),
        Device("PDU right", [300], DeviceNotReady("timeout")),
    ]
    started = time.monotonic()
    with pytest.raises(SystemExit):
        prepare("[monitoring]\ninit_timeout=600\n", *devices)
    assert time.monotonic() - started < 10
    assert "Monitoring/PDU left: Invalid credentials for https://pdu" in caplog.text
    assert "Monitoring/PDU right: timeout, attempts stopped as another device failed" in caplog.text
    assert "Monitoring: PDU left, PDU right not ready, stopping before the benchmarks" in caplog.text


def test_prepare_stops_on_a_source_of_the_server_failing(caplog):
    """turbostat failing is not tried again, and stops the attempts of the devices."""
    devices = [
        Device("turbostat", [], DeviceError("Missing turbostat binary, please install it.")),
        Device("BMC", [300], DeviceNotReady("timeout")),
    ]
    started = time.monotonic()
    with pytest.raises(SystemExit):
        prepare("[monitoring]\ninit_timeout=600\n", *devices)
    assert time.monotonic() - started < 10
    assert "Monitoring/turbostat: Missing turbostat binary, please install it." in caplog.text
    assert "Monitoring: turbostat, BMC not ready, stopping before the benchmarks" in caplog.text


def test_prepare_stops_on_a_fatal_error():
    """A key missing in the environment file stops hwbench from the thread of its device, the others too."""

    class MissingUsername(Device):
        def initialize(self, contexts):
            h.fatal("PDU left: username is required")

    devices = [MissingUsername("PDU left", [0]), Device("PDU right", [300], DeviceNotReady("timeout"))]
    started = time.monotonic()
    with pytest.raises(SystemExit):
        prepare("[monitoring]\ninit_timeout=600\n", *devices)
    assert time.monotonic() - started < 10
