from __future__ import annotations

import json
import pathlib

import pytest

from hwbench.environment import cooling
from hwbench.environment.ashrae import FAMILIES
from hwbench.environment.environment_file import Location
from hwbench.environment.topology import (
    TOPOLOGY_FILE,
    TopologyServer,
    find_location,
    find_server,
    label_warnings,
    load_topology,
    read_topology,
    save_topology,
    schema,
    separator_warnings,
    servers,
    topology_problems,
    topology_server,
    topology_servers,
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
    topology["version"] = 3
    assert topology_problems(topology) == ['["version"]: unknown version 3, expecting 1, 2']


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


def test_topology_server(topology):
    """The serial of the DMI is found without the spaces some firmwares pad it with."""
    assert (
        topology_server(topology, str(SAMPLE), " NODE0003  ").location.line()
        == "Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10"
    )


def test_topology_location_unknown_serial(topology, caplog):
    with pytest.raises(SystemExit):
        topology_server(topology, str(SAMPLE), "UNKNOWN")
    assert f"{SAMPLE}: the serial 'UNKNOWN' of the target machine is not in the topology" in caplog.text


@pytest.mark.parametrize("serial", [None, "  "])
def test_topology_location_without_serial(topology, caplog, serial):
    with pytest.raises(SystemExit):
        topology_server(topology, str(SAMPLE), serial)
    assert f"{SAMPLE}: the target machine has no serial in its DMI to find it in the topology" in caplog.text


def test_load_topology(topology):
    assert load_topology(str(SAMPLE)) == topology


def test_load_invalid_topology(tmp_path, topology, caplog):
    topology["version"] = 3
    invalid = tmp_path.joinpath("topology.json")
    invalid.write_text(json.dumps(topology))
    with pytest.raises(SystemExit):
        load_topology(str(invalid))
    assert (
        f'{invalid}: invalid topology, check it with tools/topology_check.py:\n  ["version"]: unknown version 3'
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


def test_ashrae_and_labels(topology):
    """Each family of classes is inherited separately, the narrowest place declaring it winning."""
    found = {server.serial: server for server in topology_servers(topology)}
    assert found["NODE0001"] == TopologyServer(
        "NODE0001",
        located("FR", "PA99", "2", "1", "A13", "10"),
        "db-01",
        {"air": "H1", "primary": "W40", "secondary": "S35"},
        {"cpu": "liquid", "memory": "liquid", "gpu": "air"},
    )
    assert found["NODE0003"].label is None
    # A label not declared, or no label, is cooled by air
    assert found["NODE0002"].cooling == {"cpu": "air", "memory": "air", "gpu": "air"}
    assert found["NODE0003"].cooling == {"cpu": "air", "memory": "air", "gpu": "air"}
    assert found["EXAMPLE0001"].ashrae == {"air": "A2", "primary": "W40", "secondary": "S40"}
    assert found["EXAMPLE0003"].ashrae == {"air": "A1", "primary": "W40", "secondary": "S40"}
    assert found["LAB0001"].ashrae == {}
    assert find_server(topology, "node0002").label == "db-02"


def test_version_1(topology):
    """A topology of the version 1, without classes nor labels, is still read."""
    del topology["topology"]["FR"]["PA99"]["@ashrae"]
    del topology["labels"]
    room = topology["topology"]["FR"]["PA99"]["2"]["1"]
    del room["@ashrae"]
    del room["A13"]["@ashrae"]
    room["A13"]["10"] = ["NODE0001", "NODE0002", "NODE0003", "NODE0004"]
    topology["version"] = 1
    assert topology_problems(topology) == []
    assert find_server(topology, "NODE0001") == TopologyServer("NODE0001", located("FR", "PA99", "2", "1", "A13", "10"))
    # In the version 1, '@ashrae' is the name of a place: here a position holding the serial H1
    room["A13"]["@ashrae"] = ["H1"]
    assert topology_problems(topology) == []
    assert find_location(topology, "H1") == located("FR", "PA99", "2", "1", "A13", "@ashrae")


def test_ashrae_problems(topology):
    room = topology["topology"]["FR"]["PA99"]["2"]["1"]
    room["@ashrae"] = ["A1", "A2"]
    room["A12"]["@ashrae"] = ["W33"]
    room["A13"]["@ashrae"] = []
    room["@B01"] = {"1": ["SRV1"]}
    assert topology_problems(topology) == [
        '["topology"]["FR"]["PA99"]["2"]["1"]: \'@B01\' starts with \'@\', kept for the ASHRAE classes of a place',
        '["topology"]["FR"]["PA99"]["2"]["1"]["@ashrae"]: \'A1\', \'A2\' are classes of the same family, '
        "a place declares one per family",
        '["topology"]["FR"]["PA99"]["2"]["1"]["A12"]["@ashrae"][0]: \'W33\' is not one of '
        "['A1', 'A2', 'A3', 'A4', 'H1', 'W17', 'W27', 'W32', 'W40', 'W45', 'W+', 'S30', 'S35', 'S40', 'S45', 'S50']",
        '["topology"]["FR"]["PA99"]["2"]["1"]["A13"]["@ashrae"]: [] should be non-empty',
    ]


def test_server_problems(topology):
    """A server is a serial or an object with its serial and its label: the error of the form it is written in."""
    servers = topology["topology"]["FR"]["PA99"]["2"]["1"]["A13"]["10"]
    servers[0] = {"serial": "NODE0001", "rack": "A13"}
    servers[1] = {"label": "db-02"}
    servers[2] = " NODE0003"
    servers[3] = {"serial": "NODE0004", "label": ""}
    where = '["topology"]["FR"]["PA99"]["2"]["1"]["A13"]["10"]'
    assert topology_problems(topology) == [
        f"{where}[0]: Additional properties are not allowed ('rack' was unexpected)",
        f"{where}[1]: 'serial' is a required property",
        f"{where}[2]: ' NODE0003' has spaces at its ends",
        f"{where}[3]: a name cannot be empty",
    ]


def test_cooling_problems(topology):
    """A label declares the cooling of the components hwbench monitors, each by air or by a liquid."""
    topology["labels"] = {"db-01": {"cpu": "water"}, "db-02": {"psu": "liquid"}, " db-03": {}}
    assert topology_problems(topology) == [
        "[\"labels\"]: ' db-03' has spaces at its ends",
        "[\"labels\"][\"db-01\"][\"cpu\"]: 'water' is not one of ['air', 'liquid']",
        '["labels"]["db-02"]: Additional properties are not allowed (\'psu\' was unexpected)',
    ]


def test_label_warnings(topology, caplog, tmp_path):
    """A label declaring a cooling no server has is probably misspelled."""
    assert label_warnings(topology) == []
    topology["labels"]["db-1"] = {"cpu": "liquid"}
    warning = "the label 'db-1' declares the cooling of its servers, but no server has it"
    assert label_warnings(topology) == [warning]
    misspelled = tmp_path.joinpath("topology.json")
    misspelled.write_text(json.dumps(topology))
    load_topology(str(misspelled))
    assert f"{misspelled}: {warning}" in caplog.text


def test_schema_cooling():
    """The schema accepts the components and the modes of cooling.py, its source of truth."""
    definitions = schema(2)["$defs"]
    assert list(definitions["cooling"]["properties"]) == cooling.COMPONENTS
    assert definitions["cooling_mode"]["enum"] == cooling.MODES


def test_schema_classes():
    """The schema accepts the classes of ashrae.FAMILIES, its source of truth."""
    assert schema(2)["$defs"]["ashrae"]["items"]["enum"] == [name for classes in FAMILIES.values() for name in classes]
