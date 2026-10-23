from __future__ import annotations

import socket
from typing import Any

import cachetools.func
from snmp import Engine, ErrorResponse, ImproperResponse, SNMPv2c, Timeout, UDP_IPv4, UDP_IPv6
from snmp.exception import SNMPException
from snmp.smi import Counter64, Integer32, Unsigned32

from hwbench.bench.monitoring_structs import CDUMetric, CDUSample
from hwbench.environment.vendors.cdu import CDU, CDUProtocol
from hwbench.utils import helpers as h


class SNMPv2cCDU(CDU):
    """One read-only, batched SNMPv2c GET per snapshot; no implicit retries."""

    SUPPORTED_PROTOCOLS = frozenset({CDUProtocol.SNMP_V2C})

    def __init__(self, vendor, section: str, manufacturer: str, model: str, metrics: dict[str, CDUMetric]):
        super().__init__(vendor, section)
        config = vendor.monitoring_config_file
        self.port = config.getint(section, "port", fallback=161)
        if not 1 <= self.port <= 65535:
            h.fatal(f"CDU {section}: a valid UDP port is required")
        self.community = config.get(section, "community", raw=True, fallback="")
        if not self.community:
            h.fatal(f"CDU {section}: missing SNMP_V2C read community")
        self.manufacturer = manufacturer
        self.model = model
        self.metrics = metrics.copy()

    def get_metrics(self) -> dict[str, CDUMetric]:
        return self.metrics.copy()

    def get_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"snmp://{host}:{self.port}"

    @cachetools.func.ttl_cache(maxsize=128, ttl=1.5)
    def _query(self):
        family, _, _, _, address = socket.getaddrinfo(
            self.host,
            self.port,
            type=socket.SOCK_DGRAM,
            proto=socket.IPPROTO_UDP,
        )[0]
        domain = UDP_IPv6 if family == socket.AF_INET6 else UDP_IPv4
        # Engine is not thread-safe: keep it local to this request.
        engine = Engine(SNMPv2c)
        try:
            manager = engine.Manager(address[:2], domain=domain, community=self.community.encode())
            # A refresh period beyond the deadline prevents automatic retransmits.
            return manager.get(
                *(spec.oid for spec in self.metrics.values()),
                timeout=self.timeout,
                refreshPeriod=self.timeout + 1,
                wait=True,
            )
        finally:
            # The library releases its sockets when the owning Engine is dropped.
            del engine

    def sample(self) -> CDUSample:
        errors: dict[str, str] = {}
        bindings: Any = ()
        try:
            bindings = self._query()
        except ImproperResponse as error:
            # Preserve valid readings in a partial or reordered response.
            bindings = error.variableBindings
        except Timeout:
            errors = dict.fromkeys(self.metrics, "timeout")
        except ErrorResponse:
            errors = dict.fromkeys(self.metrics, "snmp_error")
        except OSError:
            errors = dict.fromkeys(self.metrics, "transport_error")
        except SNMPException:
            errors = dict.fromkeys(self.metrics, "snmp_error")
        raw = {
            str(vb.name): vb.value.value for vb in bindings if isinstance(vb.value, (Integer32, Unsigned32, Counter64))
        }
        if not errors:
            errors = {key: "missing_or_invalid_oid" for key, spec in self.metrics.items() if spec.oid not in raw}
        values = {key: raw[spec.oid] * spec.scale if key not in errors else None for key, spec in self.metrics.items()}
        return CDUSample(values, errors)
