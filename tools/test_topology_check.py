from __future__ import annotations

import json
import pathlib

import pytest
from topology_check import main

from hwbench.environment.topology import schema_path

SAMPLE = str(pathlib.Path(__file__).parents[1].joinpath("topology.json"))


def test_valid(capsys):
    assert main([SAMPLE]) == 0
    assert capsys.readouterr().out == (
        f"{SAMPLE}: valid topology, version 1, the levels Country / Datacenter / Datahall / Room / Rack / Position: 9 servers\n"
    )


@pytest.mark.parametrize(
    ("serial", "location"),
    [
        ("NODE0003", "Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10"),
        ("EXAMPLE0003", "Country FR / Datacenter PA99 / Datahall 3 / Rack B01"),
        ("LAB0002", "Secret Lab 1"),
    ],
)
def test_serial(capsys, serial, location):
    assert main([SAMPLE, "--serial", serial]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"{serial}: {location}"


def test_unknown_serial(capsys):
    assert main([SAMPLE, "-s", "UNKNOWN"]) == 1
    assert capsys.readouterr().err == "UNKNOWN: not in the topology\n"


def test_invalid(tmp_path, capsys):
    topology = json.loads(pathlib.Path(SAMPLE).read_text())
    topology["topology"]["Secret Lab 2"] = ["LAB0001"]
    invalid = tmp_path.joinpath("topology.json")
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


def test_separator_warning(tmp_path, capsys):
    """A place holding the separator is valid, with a warning proposing another separator."""
    topology = json.loads(pathlib.Path(SAMPLE).read_text())
    topology["topology"]["Lab | 2"] = ["LAB0003"]
    topology["separator"] = "|"
    ambiguous = tmp_path.joinpath("topology.json")
    ambiguous.write_text(json.dumps(topology))
    assert main([str(ambiguous)]) == 0
    assert capsys.readouterr().err == (
        f"{ambiguous}: warning: [\"topology\"]: the place 'Lab | 2' holds the separator '|', "
        "its locations are ambiguous: give another one with \"separator\", like '>'\n"
    )
