from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from hwbench.bench.cdu_monitoring import CDUMonitoring
from hwbench.bench.monitoring import Monitoring
from hwbench.bench.monitoring_structs import CDUMetric, CDUSample, MonitoringData
from hwbench.environment.vendors.cdu import CDUProtocol


class FakeCDU:
    timeout = 2.0

    def __init__(self, name="cooling"):
        self.name = name
        self.calls = 0

    def get_name(self):
        return self.name

    def get_metrics(self):
        return {"temperature": CDUMetric("Temperature", "1.2.3", "Celsius")}

    def sample(self):
        self.calls += 1
        return CDUSample({"temperature": 20}, {})


def test_every_poll_collects_each_cdu():
    cdus = [FakeCDU("first"), FakeCDU("second")]
    monitor = CDUMonitoring(cdus)
    for _ in range(5):
        monitor.poll()
    assert [cdu.calls for cdu in cdus] == [5, 5]


def test_windows_keep_gaps_partial_failures_and_valid_zero():
    cdu = FakeCDU()
    monitor = CDUMonitoring([cdu])
    responses = iter(
        [
            CDUSample({"temperature": 20}, {}),
            CDUSample({"temperature": 24}, {}),
            CDUSample({"temperature": None}, {"temperature": "timeout"}),
            CDUSample({"temperature": 0}, {}),
            CDUSample({"temperature": None}, {"temperature": "timeout"}),
        ]
    )
    cdu.sample = lambda: next(responses)
    monitor.poll()
    monitor.poll()
    monitor.compact()
    monitor.poll()
    monitor.compact()
    monitor.poll()
    monitor.poll()
    monitor.compact()
    monitor.compact()  # No poll within this window.
    metric = monitor.data["cooling"].readings["temperature"]
    assert metric.mean == [22, None, 0, None]
    assert metric.min == [20, None, 0, None]
    assert metric.max == [24, None, 0, None]
    assert metric.samples == [2, 0, 1, 0]
    assert metric.errors == [{}, {"timeout": 1}, {"timeout": 1}, {}]
    assert metric.stdev[0] > 0
    assert metric.stdev[1:] == [None, 0, None]
    serialized = dataclasses.asdict(monitor.data["cooling"])
    assert set(serialized) == {"timeout_s", "metrics", "readings"}
    assert "timestamp" not in str(serialized)


def test_driver_exception_is_isolated_and_reset_clears_previous_run(caplog):
    broken, healthy = FakeCDU("broken"), FakeCDU("healthy")

    def fail():
        raise RuntimeError("secret-must-not-appear")

    broken.sample = fail
    monitor = CDUMonitoring([broken, healthy])
    monitor.poll()
    monitor.compact()
    assert monitor.data["broken"].readings["temperature"].errors == [{"driver_error": 1}]
    assert monitor.data["broken"].readings["temperature"].mean == [None]
    assert monitor.data["healthy"].readings["temperature"].mean == [20]
    assert "secret-must-not-appear" not in caplog.text
    monitor.reset()
    assert monitor.data["healthy"].readings["temperature"].mean == []
    monitor.poll()
    assert healthy.calls == 2


def test_cdu_and_host_compact_in_same_loop(monkeypatch):
    cdu = FakeCDU()
    monitor = Monitoring.__new__(Monitoring)
    monitor.metrics = MonitoringData()
    monitor.cdu_monitoring = CDUMonitoring([cdu])
    monitor.vendor = SimpleNamespace(get_cdus=lambda: [cdu], get_pdus=lambda: [])
    monitor.turbostat = monitor.all_smi = None
    now = [0.0]
    monkeypatch.setattr("hwbench.bench.monitoring.time.monotonic_ns", lambda: int(now[0] * 1e9))
    monkeypatch.setattr("hwbench.bench.monitoring.time.sleep", lambda duration: now.__setitem__(0, now[0] + duration))
    monkeypatch.setattr(monitor, "_Monitoring__monitor_bmc", lambda: None)
    monkeypatch.setattr(monitor, "_Monitoring__get_metrics", lambda: monitor.metrics)
    data = monitor._Monitoring__monitor(2, 5, 30)
    metric = data.cdus["cooling"].readings["temperature"]
    assert data.metadata.samples_count == 3
    assert len(data.contexts.Monitor.BMC["Polling"].mean) == 3
    assert len(data.contexts.Monitor.CDU["Polling"].mean) == 3
    assert metric.mean == [20, 20, 20]
    assert metric.samples == [5, 5, 5]
    # Final unaggregated poll is omitted exactly as for host metrics.
    assert cdu.calls == 16


def checked(*cdus):
    """A Monitoring reading only these CDUs."""
    monitor = Monitoring.__new__(Monitoring)
    monitor.vendor = SimpleNamespace(get_cdus=lambda: list(cdus))
    return monitor


class SampledCDU(FakeCDU):
    def __init__(self, sample):
        super().__init__()
        self.response = sample

    def get_metrics(self):
        return {key: CDUMetric(key, "1.2.3", "Celsius") for key in ("supply", "return")}

    def sample(self):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_prepare_reads_each_cdu(capsys):
    """Monitoring.prepare() reads each CDU once, as the BMC and the PDUs."""
    cdu = SampledCDU(CDUSample({"supply": 20.5, "return": None}, {"return": "timeout"}))
    checked(cdu).check_cdus()
    assert cdu.calls == 1
    assert "Monitoring/CDU: cooling: 1/2 metrics read" in capsys.readouterr().out


def test_prepare_stops_on_a_cdu_without_reading(caplog):
    """A CDU giving no reading, unreachable or with a wrong community, stops hwbench before the benchmarks."""
    cdu = SampledCDU(CDUSample({"supply": None, "return": None}, {"supply": "timeout", "return": "timeout"}))
    with pytest.raises(SystemExit):
        checked(cdu).check_cdus()
    assert "Monitoring/CDU: cooling: cannot read any metric: timeout" in caplog.text


def test_prepare_hints_at_the_community_of_an_snmp_v2c_cdu_timing_out(caplog):
    """An SNMPv2c agent does not answer a wrong community: it times out as an unreachable host."""
    cdu = SampledCDU(CDUSample({"supply": None, "return": None}, {"supply": "timeout", "return": "timeout"}))
    cdu.protocol, cdu.host = CDUProtocol.SNMP_V2C, "cdu.example.net"
    with pytest.raises(SystemExit):
        checked(cdu).check_cdus()
    assert (
        "Monitoring/CDU: cooling: cannot read any metric: timeout: no answer from cdu.example.net within 2s, "
        "the community is probably wrong, or the host unreachable"
    ) in caplog.text


def test_prepare_stops_on_a_failing_cdu_without_its_credentials(caplog):
    cdu = SampledCDU(RuntimeError("community=secret-community refused"))
    with pytest.raises(SystemExit):
        checked(cdu).check_cdus()
    assert "Monitoring/CDU: cooling: collection failed" in caplog.text
    assert "secret-community" not in caplog.text
