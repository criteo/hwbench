from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from hwbench.bench.monitoring_structs import MonitoringContexts

from .vendors.bmc import BMC
from .vendors.dell.dell import IDRAC
from .vendors.hpe.hpe import ILO


def idrac() -> IDRAC:
    bmc = IDRAC(pathlib.Path(""), None)
    # The OEM endpoint is found when the monitoring starts, before any timeout
    bmc.oem_endpoint = "/redfish/v1/Managers/iDRAC.Embedded.1/Attributes"
    return bmc


def ilo():
    # Untyped like the other tests building an ILO: the monitoring reads need no vendor nor ilorest
    return ILO(pathlib.Path(""), None, None)


@pytest.mark.parametrize(
    ("bmc", "multinode"),
    [
        (lambda: BMC(pathlib.Path(""), None), False),
        (ilo, False),
        (ilo, True),
        (idrac, False),
    ],
    ids=["generic", "hpe", "hpe-multinode", "dell"],
)
def test_bmc_not_answering(bmc, multinode):
    """A BMC not answering in time gives no reading: the monitoring thread died on the read timeout of an iLO."""
    bmc = bmc()
    contexts = MonitoringContexts()
    chassis = {"1": "/redfish/v1/Chassis/1/Item"}
    # get_redfish_url() returns an empty dict when the BMC does not answer in time
    with (
        patch.object(BMC, "get_redfish_url", return_value={}),
        patch.object(BMC, "_get_chassis_thermals", return_value=chassis),
        patch.object(BMC, "_get_chassis_powers", return_value=chassis),
        patch.object(ILO, "is_multinode_chassis", return_value=multinode),
    ):
        bmc.read_metrics(contexts)

    readings = [
        metric.get_values()
        for context in [contexts.Fans.Fan, contexts.PowerConsumption.BMC, contexts.PowerSupplies.BMC]
        for metric in context.values()
    ] + [metric.get_values() for sensors in contexts.Thermal.values() for metric in sensors.values()]
    assert all(values == [] for values in readings)
