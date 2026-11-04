from __future__ import annotations

import pytest

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment.vendors.mock import MockedBMC, MockVendor
from hwbench.environment.vendors.monitoring_device import DeviceNotReady


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
