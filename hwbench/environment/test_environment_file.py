from __future__ import annotations

import configparser

import pytest

from hwbench.environment.environment_file import (
    ENVIRONMENT_FILE,
    location_line,
    read_location,
    save_environment_file,
    split_location,
    without_passwords,
)

ENVIRONMENT = """# The credentials of the BMC
[default]
username=Administrator
password=secret
type=BMC

[PDU_1]
username=admin
Password : secret
  continued
type=PDU
#password=commented
url=http://mypdu/
"""


def test_without_passwords():
    """The password keys are removed, whatever their case, separator, comment or continuation lines."""
    assert (
        without_passwords(ENVIRONMENT)
        == """# The credentials of the BMC
[default]
username=Administrator
type=BMC

[PDU_1]
username=admin
type=PDU
url=http://mypdu/
"""
    )


def test_without_passwords_keeps_the_other_keys():
    """Every other key and value is still read the same."""
    original = configparser.ConfigParser(allow_no_value=True)
    original.read_string(ENVIRONMENT)
    saved = configparser.ConfigParser(allow_no_value=True)
    saved.read_string(without_passwords(ENVIRONMENT))
    for section in original.sections():
        expected = {key: value for key, value in original.items(section) if key != "password"}
        assert dict(saved.items(section)) == expected


def test_save_environment_file(tmp_path):
    environment = tmp_path / "my_environment.cfg"
    environment.write_text(ENVIRONMENT)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    save_environment_file(str(environment), out_dir)
    saved = (out_dir / ENVIRONMENT_FILE).read_text()
    assert "secret" not in saved
    assert saved == without_passwords(ENVIRONMENT)


def test_save_missing_environment_file(tmp_path, caplog):
    with pytest.raises(SystemExit):
        save_environment_file(str(tmp_path / "missing.cfg"), tmp_path)
    assert f"Cannot save the environment file '{tmp_path / 'missing.cfg'}'" in caplog.text


def environment_file(tmp_path, content: str) -> str:
    environment = tmp_path / "environment.cfg"
    environment.write_text(ENVIRONMENT + content)
    return str(environment)


def test_read_location(tmp_path):
    """The keys set, in the order of importance whatever their order and case in the file, stripped."""
    location = read_location(
        environment_file(
            tmp_path,
            """
[Location]
U=23
Rack=A12
Room=
#Datahall=DH2
COUNTRY=FR
Datacenter=PA99
""",
        )
    )
    assert list(location.items()) == [
        ("Country", "FR"),
        ("Datacenter", "PA99"),
        ("Rack", "A12"),
        ("U", "23"),
    ]


def test_read_location_extra(tmp_path):
    """Extra is set alone, when the hierarchy does not match where the server is."""
    assert read_location(environment_file(tmp_path, "\n[Location]\nextra = Secret Lab 1\n")) == {
        "Extra": "Secret Lab 1"
    }


@pytest.mark.parametrize("content", ["", "\n[Location]\n", "\n[Location]\nCountry=\n#Rack=A12\n"])
def test_read_no_location(tmp_path, content):
    """Without a [Location] section, or without any key set in it, the server has no location."""
    assert read_location(environment_file(tmp_path, content)) == {}
    assert location_line({}) is None


def test_read_location_unknown_key(tmp_path, caplog):
    environment = environment_file(tmp_path, "\n[Location]\nBuilding=B1\n")
    with pytest.raises(SystemExit):
        read_location(environment)
    assert (
        f"{environment}: unknown key 'building' in the [Location] section, expecting Country, Datacenter, Datahall, Room, Rack, U, Extra"
        in caplog.text
    )


def test_location_line():
    location = {"Country": "FR", "Datacenter": "PA99", "Datahall": "DH2", "Room": "Cage 1", "Rack": "A12", "U": "23"}
    assert location_line(location) == "FR / PA99 / DH2 / Cage 1 / Rack A12 / U23"
    assert location_line({"Rack": "A12", "U": "23"}) == "Rack A12 / U23"
    assert location_line({"Extra": "Secret Lab 1"}) == "Secret Lab 1"


def test_split_location():
    """The wide part is the place shared with other servers, up to the rack; the fine part, the height and Extra."""
    assert split_location({"Rack": "A12", "U": "23", "Extra": "Secret Lab 1"}) == (
        {"Rack": "A12"},
        {"U": "23", "Extra": "Secret Lab 1"},
    )
    assert split_location({"U": "23", "Extra": "Secret Lab 1"}) == ({}, {"U": "23", "Extra": "Secret Lab 1"})
    assert split_location({}) == ({}, {})


def test_split_location_extra_alone():
    """Extra set alone is the place the server shares with others: the wide part."""
    assert split_location({"Extra": "Secret Lab 1"}) == ({"Extra": "Secret Lab 1"}, {})
