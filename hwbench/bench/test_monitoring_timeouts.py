from __future__ import annotations

from types import SimpleNamespace

from hwbench.bench.cdu_monitoring import CDUMonitoring
from hwbench.bench.monitoring import Monitoring
from hwbench.bench.monitoring_structs import MonitoringData


class FakeDevice:
    """A device not answering in time on the iterations listed in <timeouts>."""

    def __init__(self, timeouts: dict[int, int]):
        self.timeouts = 0
        self.iteration = 0
        self.timeouts_at = timeouts

    def read(self, *_args) -> None:
        self.timeouts += self.timeouts_at.get(self.iteration, 0)
        self.iteration += 1


def test_timeouts_per_iteration(monkeypatch):
    """The Redfish requests not answered in time are saved per iteration, for the BMC and all the PDUs."""
    bmc = FakeDevice({1: 2, 7: 1})
    pdus = [FakeDevice({1: 1}), FakeDevice({1: 1, 6: 3})]
    bmc.read_metrics = bmc.read  # type: ignore[attr-defined]
    for pdu in pdus:
        pdu.read_power_consumption = pdu.read  # type: ignore[attr-defined]
    monitor = Monitoring.__new__(Monitoring)
    monitor.metrics = MonitoringData()
    monitor.vendor = SimpleNamespace(get_bmc=lambda: bmc, get_pdus=lambda: pdus, get_cdus=lambda: [])
    monitor.turbostat = monitor.all_smi = None
    monitor.cdu_monitoring = CDUMonitoring([])
    now = [0.0]
    monkeypatch.setattr("hwbench.bench.monitoring.time.monotonic_ns", lambda: int(now[0] * 1e9))
    monkeypatch.setattr("hwbench.bench.monitoring.time.sleep", lambda duration: now.__setitem__(0, now[0] + duration))
    monkeypatch.setattr(monitor, "_Monitoring__get_metrics", lambda: monitor.metrics)
    data = monitor._Monitoring__monitor(2, 5, 20)  # type: ignore[attr-defined]
    bmc_timeouts = data.contexts.Monitor.BMC["Timeouts"]
    pdu_timeouts = data.contexts.Monitor.PDU["Timeouts"]
    assert bmc_timeouts.max == [2, 1]
    assert bmc_timeouts.samples == [5, 5]
    assert [round(mean * 5) for mean in bmc_timeouts.mean] == [2, 1]
    assert pdu_timeouts.max == [2, 3]
    assert [round(mean * 5) for mean in pdu_timeouts.mean] == [2, 3]
