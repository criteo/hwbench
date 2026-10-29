from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from hwbench.bench.cdu_monitoring import CDUMonitoring
from hwbench.bench.monitoring import Monitoring
from hwbench.bench.monitoring_structs import CDUSample, MonitoringData, MonitorMetric
from hwbench.environment.vendors.monitoring_device import MonitoringDevice

# The time each fake device takes to be read, in seconds
READ_S = 0.3


class SlowDevice:
    """A BMC or a PDU taking READ_S to be read, remembering the threads reading it."""

    def __init__(self):
        self.threads: list[str] = []

    def read(self, *args):
        self.threads.append(threading.current_thread().name)
        time.sleep(READ_S)

    read_metrics = read
    read_power_consumption = read


class SlowCDU:
    timeout = 2.0

    def get_name(self):
        return "cooling"

    def get_metrics(self):
        return {}

    def sample(self):
        time.sleep(READ_S)
        return CDUSample({}, {})


def monitoring(bmc, pdus, cdus):
    monitor = Monitoring.__new__(Monitoring)
    monitor.metrics = MonitoringData()
    monitor.vendor = SimpleNamespace(get_bmc=lambda: bmc, get_pdus=lambda: pdus, get_cdus=lambda: cdus)
    monitor.cdu_monitoring = CDUMonitoring(cdus)
    for kind in ("BMC", "PDU", "CDU"):
        setattr(monitor.metrics.contexts.Monitor, kind, {"Polling": MonitorMetric("Polling", "ms")})
    return monitor


def test_devices_are_read_at_the_same_time():
    """The BMC, each PDU and the CDUs are read each in its thread: the time of an iteration is the one
    of the slowest device, the devices do not add up."""
    bmc, pdus = SlowDevice(), [SlowDevice(), SlowDevice()]
    monitor = monitoring(bmc, pdus, [SlowCDU()])
    assert monitor._Monitoring__devices_count() == 4
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=monitor._Monitoring__devices_count()) as devices:
        polling = monitor._Monitoring__start_devices_polling(devices)
        times = {id(metrics): [future.result() for future in futures] for metrics, futures in polling}
    assert time.monotonic() - start < 2 * READ_S
    contexts = monitor.metrics.contexts.Monitor
    assert [len(times[id(metrics)]) for metrics in (contexts.BMC, contexts.PDU, contexts.CDU)] == [1, 2, 1]
    assert all(READ_S * 1e3 <= value < 2 * READ_S * 1e3 for values in times.values() for value in values)
    # Each device is read by a thread of the pool, not by the monitoring one
    assert len({*bmc.threads, *pdus[0].threads, *pdus[1].threads}) == 3


def test_without_pdu_nor_cdu():
    """Only the BMC is read when there is no PDU nor CDU."""
    monitor = monitoring(SlowDevice(), [], [])
    assert monitor._Monitoring__devices_count() == 1
    with ThreadPoolExecutor(max_workers=1) as devices:
        polling = monitor._Monitoring__start_devices_polling(devices)
        assert [metrics for metrics, _ in polling] == [monitor.metrics.contexts.Monitor.BMC]


class RedfishDevice(MonitoringDevice):
    """A device whose Redfish answers count the requests reaching it."""

    def __init__(self):
        super().__init__(None)
        self.requests = 0
        outer = self

        class Session:
            def get(self, url, _):
                outer.requests += 1
                return SimpleNamespace(dict={"url": url})

        self.redfish_obj = Session()

    def read_metrics(self, _):
        # The thermal resource gives the temperatures and the fans
        self.get_redfish_url("/redfish/v1/Chassis/1/Thermal")
        self.get_redfish_url("/redfish/v1/Chassis/1/Thermal")


def test_redfish_cache_lasts_one_iteration():
    """An url read twice in an iteration is requested once, and again by the next iteration, however close."""
    bmc = RedfishDevice()
    monitor = monitoring(bmc, [], [])
    with ThreadPoolExecutor(max_workers=1) as devices:
        for _ in range(2):
            for _, futures in monitor._Monitoring__start_devices_polling(devices):
                for future in futures:
                    future.result()
    assert bmc.requests == 2
