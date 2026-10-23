from __future__ import annotations

import logging
from collections import Counter

from hwbench.environment.vendors.cdu import CDU

from .monitoring_structs import CDUAggregate, CDUMonitoringData, CDUSample


class CDUMonitoring:
    """Poll in the host loop and compact at the host's aggregation boundaries."""

    def __init__(self, cdus: list[CDU]):
        self.cdus = cdus
        self.reset()

    def reset(self) -> None:
        self.data = {
            cdu.get_name(): CDUMonitoringData(
                cdu.timeout, cdu.get_metrics(), {key: CDUAggregate() for key in cdu.get_metrics()}
            )
            for cdu in self.cdus
        }
        self.values: dict[str, dict[str, list[float]]] = {
            name: {key: [] for key in data.metrics} for name, data in self.data.items()
        }
        self.errors: dict[str, dict[str, Counter[str]]] = {
            name: {key: Counter() for key in data.metrics} for name, data in self.data.items()
        }

    def poll(self) -> None:
        for cdu in self.cdus:
            name = cdu.get_name()
            try:
                sample = cdu.sample()
            except Exception:
                # Never expose credentials contained in driver exception messages.
                logging.warning("Monitoring/CDU: %s: collection failed", name)
                sample = CDUSample({}, dict.fromkeys(self.data[name].metrics, "driver_error"))
            for key in self.data[name].metrics:
                value = sample.values.get(key)
                if value is not None:
                    self.values[name][key].append(value)
                if key in sample.errors:
                    self.errors[name][key][sample.errors[key]] += 1

    def compact(self) -> None:
        for name, data in self.data.items():
            for key, aggregate in data.readings.items():
                aggregate.compact(self.values[name][key], self.errors[name][key])
                self.values[name][key].clear()
                self.errors[name][key].clear()
