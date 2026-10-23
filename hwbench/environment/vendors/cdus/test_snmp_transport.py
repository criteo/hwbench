from __future__ import annotations

import configparser
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from snmp import SNMPv2c
from snmp.message import Message
from snmp.pdu import GetRequestPDU, ResponsePDU
from snmp.smi import Integer32, NoSuchInstance, VarBind, VarBindList

from hwbench.bench.monitoring_structs import CDUMetric
from hwbench.environment.vendors.cdus.snmp import SNMPv2cCDU

METRICS = {
    "temperature": CDUMetric("Temperature", "1.3.6.1.4.1.99999.1.0", "Celsius", 0.1),
    "pressure": CDUMetric("Pressure", "1.3.6.1.4.1.99999.2.0", "raw"),
}


def make_cdu(port, timeout=0.2):
    config = configparser.ConfigParser()
    config.read_dict(
        {
            "wire-test": {
                "protocol": "SNMP_V2C",
                "host": "127.0.0.1",
                "port": str(port),
                "timeout": str(timeout),
                "community": "wire-test",
            }
        }
    )
    return SNMPv2cCDU(SimpleNamespace(monitoring_config_file=config), "wire-test", "EXAMPLE", "fixture", METRICS)


def reply(sock, count=1, partial=False):
    for _ in range(count):
        data, peer = sock.recvfrom(65535)
        message = Message.decodeExact(data, types={GetRequestPDU.TAG: GetRequestPDU})
        assert message.version == SNMPv2c
        assert message.community == b"wire-test"
        assert [str(vb.name) for vb in message.pdu.variableBindings] == [spec.oid for spec in METRICS.values()]
        bindings = VarBindList(
            VarBind(METRICS["temperature"].oid, Integer32(215)),
            VarBind(METRICS["pressure"].oid, NoSuchInstance() if partial else Integer32(123)),
        )
        response = ResponsePDU(requestID=message.pdu.requestID, variableBindings=bindings)
        sock.sendto(Message(SNMPv2c, message.community, response).encode(), peer)


@pytest.mark.parametrize("partial", [False, True])
def test_udp_batched_get_and_typed_response(partial):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, ThreadPoolExecutor(max_workers=1) as pool:
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(2)
        future = pool.submit(reply, sock, partial=partial)
        sample = make_cdu(sock.getsockname()[1], timeout=1).sample()
        future.result(timeout=2)
    assert sample.values["temperature"] == 21.5
    if partial:
        assert sample.values["pressure"] is None
        assert sample.errors == {"pressure": "missing_or_invalid_oid"}
    else:
        assert sample.values["pressure"] == 123
        assert sample.errors == {}


def test_udp_timeout_has_no_retransmission():
    def receive(sock):
        packets = []
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                packets.append(sock.recvfrom(65535)[0])
            except TimeoutError:
                break
        return packets

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, ThreadPoolExecutor(max_workers=1) as pool:
        sock.bind(("127.0.0.1", 0))
        future = pool.submit(receive, sock)
        started = time.monotonic()
        cdu = make_cdu(sock.getsockname()[1], timeout=0.1)
        sample = cdu.sample()
        elapsed = time.monotonic() - started
        # A failed query must be retried on the next call, even within the TTL.
        assert set(cdu.sample().errors.values()) == {"timeout"}
        packets = future.result(timeout=2)
    assert len(packets) == 2
    assert set(sample.errors.values()) == {"timeout"}
    assert all(value is None for value in sample.values.values())
    assert elapsed < 0.7


def test_udp_requests_release_their_sockets():
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("Descriptor counts are available on Linux")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, ThreadPoolExecutor(max_workers=1) as pool:
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(2)
        future = pool.submit(reply, sock, count=21)
        cdu = make_cdu(sock.getsockname()[1], timeout=1)
        assert not cdu.sample().errors
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(20):
            cdu._query.cache_clear()
            assert not cdu.sample().errors
        assert len(os.listdir("/proc/self/fd")) <= before + 1
        future.result(timeout=2)


def test_udp_cache_reuses_responses_expires_and_isolates_devices():
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as first,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as second,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        for sock in (first, second):
            sock.bind(("127.0.0.1", 0))
            sock.settimeout(2)
        first_reply = pool.submit(reply, first, count=2)
        second_reply = pool.submit(reply, second)
        cdu = make_cdu(first.getsockname()[1], timeout=1)
        other = make_cdu(second.getsockname()[1], timeout=1)
        initial = cdu.sample()
        assert not initial.errors
        assert cdu.sample().values == initial.values
        # Different instances must issue their own request.
        assert not other.sample().errors
        cache = cdu._query.cache
        assert cache.ttl == 1.5
        # Expire through the public cache API, avoiding timing-dependent sleeps.
        cache.expire(time=cache.timer() + cache.ttl)
        assert not cdu.sample().errors
        first_reply.result(timeout=2)
        second_reply.result(timeout=2)
