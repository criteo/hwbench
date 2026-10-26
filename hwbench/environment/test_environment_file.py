from __future__ import annotations

import configparser

import pytest

from hwbench.environment.environment_file import (
    ENVIRONMENT_FILE,
    Location,
    read_location,
    save_environment_file,
    without_passwords,
)
from hwbench.environment.vendors.generic import GenericVendor

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

[PDU_2]
password = first

# continued past the blank and comment lines
  secret
url=http://mypdu2/
# the end of the file
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

[PDU_2]
url=http://mypdu2/
# the end of the file
"""
    )


def test_without_communities():
    """The SNMP community of a CDU is a secret too: removed like the passwords."""
    cdu = "[CDU_cooling]\ntype=CDU\nprotocol=SNMP_V2C\nCommunity = example-read-community\n#community=old\nhost=cdu\n"
    assert without_passwords(cdu) == "[CDU_cooling]\ntype=CDU\nprotocol=SNMP_V2C\nhost=cdu\n"


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
    environment = tmp_path.joinpath("my_environment.cfg")
    environment.write_text(ENVIRONMENT)
    out_dir = tmp_path.joinpath("out")
    out_dir.mkdir()
    save_environment_file(str(environment), out_dir)
    saved = out_dir.joinpath(ENVIRONMENT_FILE).read_text()
    assert "secret" not in saved
    assert saved == without_passwords(ENVIRONMENT)


def test_no_interpolation(tmp_path):
    """A password is read as written: it cannot take its value from a key the saved environment file keeps."""
    environment_file = tmp_path.joinpath("environment.cfg")
    environment_file.write_text("[DEFAULT]\npw=secret\n[default]\npassword=%(pw)s\ntype=BMC\n")
    vendor = GenericVendor(tmp_path, None, str(environment_file))
    assert vendor.find_monitoring_sections("BMC") == ["default"]
    assert vendor.monitoring_config_file.get("default", "password") == "%(pw)s"


def test_save_missing_environment_file(tmp_path, caplog):
    with pytest.raises(SystemExit):
        save_environment_file(str(tmp_path.joinpath("missing.cfg")), tmp_path)
    assert f"Cannot save the environment file '{tmp_path.joinpath('missing.cfg')}'" in caplog.text


def environment_file(tmp_path, content: str) -> str:
    environment = tmp_path.joinpath("environment.cfg")
    environment.write_text(ENVIRONMENT + content)
    return str(environment)


def test_read_location(tmp_path):
    """The places and the names of the levels, cut on '/' and stripped, whatever the case of the section."""
    location = read_location(
        environment_file(
            tmp_path,
            """
[LOCATION]
levels = Country / DC / DH / Room / Rack / Position
location = FR / PA3 / 12.34 / LH1234.12 / 12.23 / 3
""",
        )
    )
    assert location == Location(
        ["FR", "PA3", "12.34", "LH1234.12", "12.23", "3"], "/", ["Country", "DC", "DH", "Room", "Rack", "Position"]
    )
    assert location.line() == "Country FR / DC PA3 / DH 12.34 / Room LH1234.12 / Rack 12.23 / Position 3"


def test_read_location_separator(tmp_path):
    """The separator cuts both keys and is shown between the places, the places not known are not shown."""
    location = read_location(
        environment_file(tmp_path, "\n[Location]\nseparator = ,\nlevels = DC, Room, Rack\nlocation = PA3, , A12\n")
    )
    assert location == Location(["PA3", "", "A12"], ",", ["DC", "Room", "Rack"])
    assert location.line() == "DC PA3 , Rack A12"


def test_read_location_without_levels(tmp_path):
    """The levels are optional: the location is then a path of places only, shown alone."""
    location = read_location(environment_file(tmp_path, "\n[Location]\nlocation = FR / PA3 / A12\n"))
    assert location == Location(["FR", "PA3", "A12"])
    assert location.line() == "FR / PA3 / A12"


def test_read_location_out_of_the_hierarchy(tmp_path):
    """A single place is out of the hierarchy, whatever the levels: it has none."""
    location = read_location(
        environment_file(tmp_path, "\n[Location]\nlevels = Country / DC\nlocation = Secret Lab 1\n")
    )
    assert location == Location(["Secret Lab 1"])
    assert location.line() == "Secret Lab 1"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "\n[Location]\n",
        "\n[Location]\nlevels = Country / DC\n",
        "\n[Location]\nlocation =\n",
        "\n[Location]\n#location = FR / PA3\n",
        "\n[Location]\nlocation = / \n",
    ],
)
def test_read_no_location(tmp_path, content):
    """Without a location, or without any place known, the server has no location."""
    assert read_location(environment_file(tmp_path, content)) is None


def test_read_location_with_defaults(tmp_path):
    """The keys of [DEFAULT], inherited by every section, are not unknown keys of [Location]."""
    environment = tmp_path.joinpath("environment.cfg")
    environment.write_text("[DEFAULT]\nusername=admin\n" + ENVIRONMENT + "\n[Location]\nlocation=A / B\n")
    assert read_location(str(environment)) == Location(["A", "B"])


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (
            "\n[Location]\nCountry=FR\n",
            "unknown key 'country' in the [Location] section, expecting separator, levels, location",
        ),
        (
            "\n[Location]\nlevels = DC / Rack\nlocation = FR / PA3 / A12\n",
            "the location 'FR / PA3 / A12' of the [Location] section has 3 places, "
            "expecting one for each of the 2 levels 'DC / Rack', or a single one out of the hierarchy",
        ),
        (
            "\n[Location]\nlevels = DC / / Rack\nlocation = PA3 / 1 / A12\n",
            "the levels 'DC / / Rack' of the [Location] section have an empty name",
        ),
    ],
)
def test_read_invalid_location(tmp_path, caplog, content, error):
    environment = environment_file(tmp_path, content)
    with pytest.raises(SystemExit):
        read_location(environment)
    assert f"{environment}: {error}" in caplog.text


def test_location_dict():
    """The location is kept in results.json with its separator, and its levels when known."""
    location = Location(["FR", "PA3"], "/", ["Country", "DC"])
    assert location.to_dict() == {"path": ["FR", "PA3"], "separator": "/", "levels": ["Country", "DC"]}
    assert Location.from_dict(location.to_dict()) == location
    assert Location(["Secret Lab 1"]).to_dict() == {"path": ["Secret Lab 1"], "separator": "/"}
    assert Location.from_dict({"path": ["Secret Lab 1"]}) == Location(["Secret Lab 1"])
