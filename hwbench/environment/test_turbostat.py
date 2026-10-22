from __future__ import annotations

import ast
from unittest.mock import MagicMock, patch

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment.turbostat import Turbostat


def make_turbostat(outputs: list[list[str]]) -> tuple[Turbostat, list[str]]:
    """Build a Turbostat whose successive runs print the outputs, return it with the --show of each run."""
    shows = []

    def run(self, interval: float = 1, wait=False):
        shows.append(self.show())
        return outputs[len(shows) - 1]

    with (
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
    assert shows == ["Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,IPC,CorWatt,PkgWatt"]
    assert turbostat.get_cores_count() > 0
