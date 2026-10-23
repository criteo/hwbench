from __future__ import annotations

import json
import pathlib

import pytest
from topology_check import main

from hwbench.environment.topology import schema_path

SAMPLE = str(pathlib.Path(__file__).parents[1] / "topology.json")


def test_valid(capsys):
    assert main([SAMPLE]) == 0
    assert capsys.readouterr().out == f"{SAMPLE}: valid topology, version 1: 7 servers in the topology, 2 in extra\n"


@pytest.mark.parametrize(
    ("serial", "location"),
    [
        ("NODE0003", "FR / PA99 / DH2 / Cage 1 / Rack A13 / U10"),
        ("EXAMPLE0003", "FR / PA99 / DH3 / Rack B01"),
        ("LAB0002", "Secret Lab 1"),
    ],
)
def test_serial(capsys, serial, location):
    assert main([SAMPLE, "--serial", serial]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"{serial}: {location}"


def test_unknown_serial(capsys):
    assert main([SAMPLE, "-s", "UNKNOWN"]) == 1
    assert capsys.readouterr().err == "UNKNOWN: neither in the topology nor in extra\n"


def test_invalid(tmp_path, capsys):
    topology = json.loads(pathlib.Path(SAMPLE).read_text())
    topology["extra"]["Secret Lab 2"] = ["LAB0001"]
    invalid = tmp_path / "topology.json"
    invalid.write_text(json.dumps(topology))
    assert main([str(invalid)]) == 1
    assert capsys.readouterr().err == (
        f"{invalid}: invalid topology:\n  the serial 'LAB0001' is at several places: 'Secret Lab 1', 'Secret Lab 2'\n"
    )


def test_schema(capsys):
    assert main(["--schema"]) == 0
    assert capsys.readouterr().out == f"{schema_path()}\n"


def test_missing_topology(capsys):
    with pytest.raises(SystemExit):
        main([])
    assert "the topology file is required" in capsys.readouterr().err
