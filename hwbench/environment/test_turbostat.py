from __future__ import annotations

import ast
import logging
import pathlib
from unittest.mock import MagicMock, patch

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment.turbostat import Turbostat, ram_metered


def make_turbostat(outputs: list[list[str]], ram: bool = True) -> tuple[Turbostat, list[str]]:
    """Build a Turbostat whose successive runs print the outputs, return it with the --show of each run."""
    shows = []

    def run(self, interval: float = 1, wait=False):
        shows.append(self.show())
        return outputs[len(shows) - 1]

    with (
        patch("hwbench.environment.turbostat.ram_metered", return_value=ram),
        patch("hwbench.environment.turbostat.Turbostat.check_version"),
        patch("hwbench.environment.turbostat.Turbostat.run", run),
    ):
        return Turbostat(MagicMock(), MonitoringContexts()), shows


def turbostat_output() -> list[str]:
    with open("hwbench/tests/parsing/turbostat/run") as f:
        return ast.literal_eval(f.read())


def test_columns_requested():
    """No idle state column is requested: a turbostat refuses those the processor does not have."""
    turbostat, shows = make_turbostat([turbostat_output()])
    assert shows == ["Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,IPC,CorWatt,PkgWatt,RAMWatt"]
    assert turbostat.get_cores_count() > 0


def test_optional_columns_refused(caplog):
    """A turbostat refusing an optional column, like RAMWatt, prints nothing: hwbench retries without it."""
    with caplog.at_level(logging.WARNING):
        turbostat, shows = make_turbostat([[], turbostat_output()])
    assert shows == [
        "Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,IPC,CorWatt,PkgWatt,RAMWatt",
        "Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,IPC,CorWatt,PkgWatt",
    ]
    assert "no output with the optional columns RAMWatt, retrying without them" in caplog.text
    assert turbostat.optional_columns == []
    assert turbostat.get_cores_count() > 0


# Two packages of two cores: turbostat reports PkgWatt and RAMWatt on the first cpu of each package
TWO_PACKAGES = [
    "usec\tNode\tCore\tCPU\tBzy_MHz\tCorWatt\tPkgWatt\tRAMWatt",
    "-\t-\t-\t-\t2000\t5.00\t150.00\t20.00",
    "10\t0\t0\t0\t2000\t2.00\t70.00\t9.00",
    "10\t0\t1\t1\t2000\t1.00",
    "10\t1\t0\t2\t2000\t1.00\t80.00\t11.00",
    "10\t1\t1\t3\t2000\t1.00",
]


def test_ram_watts():
    """The memory power is summed over the packages, next to the package power."""
    turbostat, _ = make_turbostat([TWO_PACKAGES])
    turbostat.parse_sample(TWO_PACKAGES)
    power = turbostat.monitoring_contexts.PowerConsumption.CPU
    assert power["package"].get_values() == [150.0]
    assert power["Ram"].get_values() == [20.0]


def make_power(tmp_path: pathlib.Path, events: list[str], domains: list[str]) -> tuple[pathlib.Path, pathlib.Path]:
    """The perf power events and the powercap domains the kernel exposes."""
    power_events = tmp_path / "events"
    power_events.mkdir(parents=True)
    for event in events:
        (power_events / event).write_text("event=0x01\n")
    powercap = tmp_path / "powercap"
    for index, domain in enumerate(domains):
        (powercap / f"intel-rapl:0:{index}").mkdir(parents=True)
        (powercap / f"intel-rapl:0:{index}" / "name").write_text(f"{domain}\n")
    return power_events, powercap


def test_ram_metered(tmp_path):
    """The memory is metered when the kernel exposes its energy, as a perf event or a powercap domain."""
    assert ram_metered(*make_power(tmp_path / "perf", ["energy-pkg", "energy-ram"], []))
    assert ram_metered(*make_power(tmp_path / "powercap", [], ["package-0", "dram"]))


def test_ram_not_metered(tmp_path):
    """An Intel Core Ultra 7 165U shows RAMWatt in turbostat, at 0 Watts, without any memory counter."""
    events = ["energy-cores", "energy-gpu", "energy-pkg", "energy-psys"]
    assert not ram_metered(*make_power(tmp_path, events, ["package-0", "core", "uncore", "psys"]))
    assert not ram_metered(tmp_path / "missing", tmp_path / "missing")
    _, shows = make_turbostat([TWO_PACKAGES], ram=False)
    assert shows == ["Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,IPC,CorWatt,PkgWatt"]


def test_without_ram_watts():
    """A processor not metering its memory has no ram power."""
    output = ["\t".join(line.split("\t")[:7]) for line in TWO_PACKAGES]
    turbostat, _ = make_turbostat([output])
    turbostat.parse_sample(output)
    assert "Ram" not in turbostat.monitoring_contexts.PowerConsumption.CPU
    assert turbostat.monitoring_contexts.PowerConsumption.CPU["package"].get_values() == [150.0]
