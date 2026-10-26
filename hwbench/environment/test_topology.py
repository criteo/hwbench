from __future__ import annotations

import json
import pathlib

import pytest

from hwbench.environment.environment_file import Location
from hwbench.environment.topology import (
    TOPOLOGY_FILE,
    find_location,
    load_topology,
    read_topology,
    save_topology,
    separator_warnings,
    servers,
    topology_location,
    topology_problems,
)

# The sample of the repository, described by documentation/topology.md
SAMPLE = pathlib.Path(__file__).parents[2].joinpath("topology.json")


@pytest.fixture
def topology() -> dict:
    return json.loads(SAMPLE.read_text())


def test_sample_is_valid(topology):
    assert topology_problems(topology) == []


LEVELS = ["Country", "Datacenter", "Datahall", "Room", "Rack", "Position"]


def located(*path: str) -> Location:
    """A location of the sample, with its levels."""
    return Location(list(path), "/", LEVELS)


def test_servers(topology):
    """Each serial with its location: the path of its places, with the levels when it is at their depth."""
    assert dict(servers(topology)) == {
        "EXAMPLE0001": located("FR", "PA99", "2", "1", "A12", "22"),
        "EXAMPLE0002": located("FR", "PA99", "2", "1", "A12", "23"),
        **{f"NODE000{node}": located("FR", "PA99", "2", "1", "A13", "10") for node in range(1, 5)},
        "EXAMPLE0003": located("FR", "PA99", "3", "", "B01", ""),
        "LAB0001": Location(["Secret Lab 1"]),
        "LAB0002": Location(["Secret Lab 1"]),
    }


def test_servers_without_levels():
    """Without levels, the serials can be at any depth, shown with the separator of the topology."""
    topology = {"version": 1, "separator": ",", "topology": {"PA3": {"A12": ["SRV1"], "A13": {"1": ["SRV2"]}}}}
    assert topology_problems(topology) == []
    assert dict(servers(topology)) == {
        "SRV1": Location(["PA3", "A12"], ","),
        "SRV2": Location(["PA3", "A13", "1"], ","),
    }


def test_find_location(topology):
    assert find_location(topology, "LAB0002") == Location(["Secret Lab 1"])
    assert find_location(topology, "UNKNOWN") is None


def test_schema_problems(topology):
    """Each problem gives where it is in the file."""
    room = topology["topology"]["FR"]["PA99"]["2"]["1"]
    room["A12"]["22"] = []
    room["A13"]["10"] = "NODE0001"
    topology["topology"]["FR"][" PA1"] = {}
    topology["levels"].append("")
    topology["owner"] = "me"
    assert topology_problems(topology) == [
        '["levels"][6]: a name cannot be empty',
        '["topology"]["FR"]: \' PA1\' has spaces at its ends',
        '["topology"]["FR"]["PA99"]["2"]["1"]["A12"]["22"]: [] should be non-empty',
        '["topology"]["FR"]["PA99"]["2"]["1"]["A13"]["10"]: \'NODE0001\' is not of type \'object\'',
        "the document: Additional properties are not allowed ('owner' was unexpected)",
    ]


def test_depth_problems(topology):
    """With levels, the serials are at their depth, or right under the root, out of the hierarchy."""
    topology["topology"]["FR"]["PA99"]["4"] = ["SRV1"]
    topology["topology"][""] = ["SRV2"]
    assert topology_problems(topology) == [
        '["topology"]["FR"]["PA99"]["4"]: serials at the level 3, expecting the 6 levels '
        "Country / Datacenter / Datahall / Room / Rack / Position, or a single place out of the hierarchy",
        '["topology"][""]: serials without any known place',
    ]


@pytest.mark.parametrize("section", ["version", "topology"])
def test_mandatory_sections(topology, section):
    del topology[section]
    assert topology_problems(topology) == [f"the document: '{section}' is a required property"]


def test_unknown_version(topology):
    topology["version"] = 2
    assert topology_problems(topology) == ['["version"]: unknown version 2, expecting 1']


def test_serial_at_several_places(topology):
    """A serial is at a single place: the schema cannot check it."""
    topology["topology"]["Secret Lab 2"] = ["EXAMPLE0002"]
    assert topology_problems(topology) == [
        "the serial 'EXAMPLE0002' is at several places: 'Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23', 'Secret Lab 2'"
    ]


def test_read_topology(tmp_path):
    broken = tmp_path.joinpath("topology.json")
    broken.write_text("{")
    assert read_topology(str(broken))[1][0].startswith("cannot read the topology: Expecting property name")
    assert read_topology(str(tmp_path.joinpath("missing.json")))[1][0].startswith("cannot read the topology: [Errno 2]")


def test_topology_location(topology):
    """The serial of the DMI is found without the spaces some firmwares pad it with."""
    assert (
        topology_location(topology, str(SAMPLE), " NODE0003  ").line()
        == "Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10"
    )


def test_topology_location_unknown_serial(topology, caplog):
    with pytest.raises(SystemExit):
        topology_location(topology, str(SAMPLE), "UNKNOWN")
    assert f"{SAMPLE}: the serial 'UNKNOWN' of the target machine is not in the topology" in caplog.text


@pytest.mark.parametrize("serial", [None, "  "])
def test_topology_location_without_serial(topology, caplog, serial):
    with pytest.raises(SystemExit):
        topology_location(topology, str(SAMPLE), serial)
    assert f"{SAMPLE}: the target machine has no serial in its DMI to find it in the topology" in caplog.text


def test_load_topology(topology):
    assert load_topology(str(SAMPLE)) == topology


def test_load_invalid_topology(tmp_path, topology, caplog):
    topology["version"] = 2
    invalid = tmp_path.joinpath("topology.json")
    invalid.write_text(json.dumps(topology))
    with pytest.raises(SystemExit):
        load_topology(str(invalid))
    assert (
        f'{invalid}: invalid topology, check it with tools/topology_check.py:\n  ["version"]: unknown version 2'
        in caplog.text
    )


def test_save_topology(tmp_path):
    save_topology(str(SAMPLE), tmp_path)
    assert tmp_path.joinpath(TOPOLOGY_FILE).read_text() == SAMPLE.read_text()


def test_serial_case(topology):
    """The serials are compared in uppercase: an inventory may not have the case of the DMI."""
    topology["topology"]["Secret Lab 1"].append("lab0003")
    assert find_location(topology, "LAB0003") == Location(["Secret Lab 1"])
    assert find_location(topology, "node0001") == located("FR", "PA99", "2", "1", "A13", "10")
    topology["topology"]["Secret Lab 2"] = ["example0002"]
    assert topology_problems(topology) == [
        "the serial 'EXAMPLE0002' is at several places: 'Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23', 'Secret Lab 2'"
    ]


def test_separator_warnings(topology, caplog, tmp_path):
    """A place holding the separator makes its locations ambiguous: another separator is proposed."""
    assert separator_warnings(topology) == []
    topology["topology"]["FR"]["PA99"]["2"]["1"]["A12/B"] = {"U1": ["SRV1"]}
    warning = (
        '["topology"]["FR"]["PA99"]["2"]["1"]: the place \'A12/B\' holds the separator \'/\', '
        "its locations are ambiguous: give another one with \"separator\", like '|'"
    )
    assert separator_warnings(topology) == [warning]
    ambiguous = tmp_path.joinpath("topology.json")
    ambiguous.write_text(json.dumps(topology))
    load_topology(str(ambiguous))
    assert f"{ambiguous}: {warning}" in caplog.text
