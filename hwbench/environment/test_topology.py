from __future__ import annotations

import json
import pathlib

import pytest

from hwbench.environment.environment_file import LOCATION_KEYS
from hwbench.environment.topology import (
    LEVELS,
    TOPOLOGY_FILE,
    find_location,
    read_topology,
    save_topology,
    schema,
    servers,
    topology_location,
    topology_problems,
)

# The sample of the repository, described by documentation/topology.md
SAMPLE = pathlib.Path(__file__).parents[2] / "topology.json"


@pytest.fixture
def topology() -> dict:
    return json.loads(SAMPLE.read_text())


def test_sample_is_valid(topology):
    assert topology_problems(topology) == []


def test_schema_levels():
    """The schema chains its levels in the order of the keys of the location, Extra having its own section."""
    definitions = schema()["$defs"]
    chain = [schema()["properties"]["topology"]["$ref"].split("/")[-1]]
    while definitions[chain[-1]]["additionalProperties"]["$ref"] != "#/$defs/serials":
        chain.append(definitions[chain[-1]]["additionalProperties"]["$ref"].split("/")[-1])
    assert chain == LEVELS == [key for key in LOCATION_KEYS if key != "Extra"]


def test_servers(topology):
    """Each serial with its location, a level named '' being not set."""
    assert dict(servers(topology)) == {
        "EXAMPLE0001": {
            "Country": "FR",
            "Datacenter": "PA99",
            "Datahall": "DH2",
            "Room": "Cage 1",
            "Rack": "A12",
            "U": "22",
        },
        "EXAMPLE0002": {
            "Country": "FR",
            "Datacenter": "PA99",
            "Datahall": "DH2",
            "Room": "Cage 1",
            "Rack": "A12",
            "U": "23",
        },
        **{
            f"NODE000{node}": {
                "Country": "FR",
                "Datacenter": "PA99",
                "Datahall": "DH2",
                "Room": "Cage 1",
                "Rack": "A13",
                "U": "10",
            }
            for node in range(1, 5)
        },
        "EXAMPLE0003": {"Country": "FR", "Datacenter": "PA99", "Datahall": "DH3", "Rack": "B01"},
        "LAB0001": {"Extra": "Secret Lab 1"},
        "LAB0002": {"Extra": "Secret Lab 1"},
    }


def test_find_location(topology):
    assert find_location(topology, "LAB0002") == {"Extra": "Secret Lab 1"}
    assert find_location(topology, "UNKNOWN") is None


def test_schema_problems(topology):
    """Each problem gives where it is in the file."""
    room = topology["topology"]["FR"]["PA99"]["DH2"]["Cage 1"]
    room["A12"]["22"] = []
    room["A13"] = ["NODE0001"]
    topology["topology"]["FR"][" PA1"] = {}
    topology["extra"][""] = ["LAB0003"]
    topology["owner"] = "me"
    assert topology_problems(topology) == [
        '["extra"]: a name cannot be empty',
        '["topology"]["FR"]: \' PA1\' has spaces at its ends',
        '["topology"]["FR"]["PA99"]["DH2"]["Cage 1"]["A12"]["22"]: [] should be non-empty',
        '["topology"]["FR"]["PA99"]["DH2"]["Cage 1"]["A13"]: [\'NODE0001\'] is not of type \'object\'',
        "the document: Additional properties are not allowed ('owner' was unexpected)",
    ]


@pytest.mark.parametrize("section", ["version", "topology", "extra"])
def test_mandatory_sections(topology, section):
    del topology[section]
    assert topology_problems(topology) == [f"the document: '{section}' is a required property"]


def test_unknown_version(topology):
    topology["version"] = 2
    assert topology_problems(topology) == ['["version"]: unknown version 2, expecting 1']


def test_serial_at_several_places(topology):
    """A serial is at a single place, in the topology or in extra: the schema cannot check it."""
    topology["extra"]["Secret Lab 2"] = ["EXAMPLE0002"]
    assert topology_problems(topology) == [
        "the serial 'EXAMPLE0002' is at several places: 'FR / PA99 / DH2 / Cage 1 / Rack A12 / U23', 'Secret Lab 2'"
    ]


def test_read_topology(tmp_path):
    broken = tmp_path / "topology.json"
    broken.write_text("{")
    assert read_topology(str(broken))[1][0].startswith("cannot read the topology: Expecting property name")
    assert read_topology(str(tmp_path / "missing.json"))[1][0].startswith("cannot read the topology: [Errno 2]")


def test_topology_location():
    assert topology_location(str(SAMPLE), "NODE0003")["Rack"] == "A13"


def test_topology_location_unknown_serial(caplog):
    with pytest.raises(SystemExit):
        topology_location(str(SAMPLE), "UNKNOWN")
    assert (
        f"{SAMPLE}: the serial 'UNKNOWN' of the target machine is neither in the topology nor in extra" in caplog.text
    )


def test_topology_location_invalid(tmp_path, topology, caplog):
    topology["version"] = 2
    invalid = tmp_path / "topology.json"
    invalid.write_text(json.dumps(topology))
    with pytest.raises(SystemExit):
        topology_location(str(invalid), "LAB0001")
    assert (
        f'{invalid}: invalid topology, check it with tools/topology_check.py:\n  ["version"]: unknown version 2'
        in caplog.text
    )


def test_save_topology(tmp_path):
    save_topology(str(SAMPLE), tmp_path)
    assert (tmp_path / TOPOLOGY_FILE).read_text() == SAMPLE.read_text()
