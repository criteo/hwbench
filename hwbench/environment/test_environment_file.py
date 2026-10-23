from __future__ import annotations

import configparser

import pytest

from hwbench.environment.environment_file import ENVIRONMENT_FILE, save_environment_file, without_passwords

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
