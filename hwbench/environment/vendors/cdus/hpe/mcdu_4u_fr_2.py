from __future__ import annotations

from hwbench.bench.monitoring_structs import CDUMetric
from hwbench.environment.vendors.cdu import CDUProtocol
from hwbench.environment.vendors.cdus.snmp import SNMPv2cCDU


def metric(name: str, suffix: str, unit: str, scale: float = 1) -> CDUMetric:
    return CDUMetric(name, "1.3.6.1.4.1.9839.2.1." + suffix + ".0", unit, scale)


# HPE MCDU-4U-FR-2 OIDs validated against the device.
# Pressure scaling is unverified: retain raw counts, not guessed bar.
METRICS = {
    "primary_supply_temperature": metric("Primary supply temperature", "2.22", "Celsius", 0.1),
    "primary_return_temperature": metric("Primary return temperature", "2.28", "Celsius", 0.1),
    "secondary_supply_temperature": metric("Secondary supply temperature", "2.19", "Celsius", 0.1),
    "secondary_return_temperature": metric("Secondary return temperature", "2.20", "Celsius", 0.1),
    "ambient_temperature": metric("Ambient temperature", "2.25", "Celsius", 0.1),
    "plc_temperature": metric("PLC temperature", "2.61", "Celsius", 0.1),
    "primary_supply_pressure": metric("Primary supply pressure", "2.1", "raw"),
    "primary_return_pressure": metric("Primary return pressure", "2.3", "raw"),
    "secondary_supply_pressure": metric("Secondary pump supply pressure", "2.32", "raw"),
    "secondary_return_pressure": metric("Secondary return pressure", "2.45", "raw"),
    "primary_flow": metric("Primary flow", "2.119", "L/min", 0.1),
    "secondary_flow": metric("Secondary flow", "2.120", "L/min", 0.1),
    "valve_position": metric("Valve position", "3.40", "Percent"),
    "humidity": metric("Relative humidity", "2.27", "Percent", 0.1),
    "pump1_rpm": metric("Pump 1 RPM", "3.110", "RPM"),
    "pump2_rpm": metric("Pump 2 RPM", "3.111", "RPM"),
}


class HPEMCDU4UFR2(SNMPv2cCDU):
    SUPPORTED_PROTOCOLS = frozenset({CDUProtocol.SNMP_V2C})

    def __init__(self, vendor, section: str):
        super().__init__(vendor, section, "HPE", "MCDU-4U-FR-2", METRICS)
