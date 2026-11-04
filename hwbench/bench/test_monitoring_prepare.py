from __future__ import annotations

from types import SimpleNamespace

import pytest

from hwbench.bench.monitoring import Monitoring
from hwbench.bench.monitoring_structs import MonitoringData
from hwbench.environment.vendors.mock import MockedBMC, MockVendor
from hwbench.environment.vendors.monitoring_device import DeviceNotReady


class SilentBMC(MockedBMC):
    """A BMC answering, without any thermal sensor yet: a BMC still booting."""

    def read_thermals(self, thermals):
        return thermals


def checked(bmc):
    """A Monitoring reading only this BMC."""
    monitor = Monitoring.__new__(Monitoring)
    monitor.metrics = MonitoringData()
    monitor.vendor = SimpleNamespace(get_bmc=lambda: bmc, get_pdus=lambda: [], get_cdus=lambda: [])
    return monitor


def test_check_bmc(capsys):
    checked(MockedBMC(None, MockVendor(None, None))).check_bmc()
    assert "Monitoring/BMC: Thermal metrics: 1xCPU" in capsys.readouterr().out


def test_check_bmc_without_metrics():
    """A BMC giving no metric may give them to a later attempt."""
    with pytest.raises(DeviceNotReady, match="Cannot detect Thermal metrics"):
        checked(SilentBMC(None, MockVendor(None, None))).check_bmc()
