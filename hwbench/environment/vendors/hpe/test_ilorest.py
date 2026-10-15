import pathlib

from .ilorest import Ilorest

BIOS = b'{\n  "AcpiHpet": "Enabled",\n  "WorkloadProfile": "Custom"\n}\n'


def test_parse_bios_with_discovering_message(tmp_path: pathlib.Path):
    """ilorest 7.4 writes 'Discovering data...Done' on stdout before the JSON."""
    stdout = b"Discovering data...Done\n" + BIOS
    assert Ilorest(tmp_path).parse_cmd(stdout, b"") == {"AcpiHpet": "Enabled", "WorkloadProfile": "Custom"}


def test_parse_bios(tmp_path: pathlib.Path):
    assert Ilorest(tmp_path).parse_cmd(BIOS, b"") == {"AcpiHpet": "Enabled", "WorkloadProfile": "Custom"}
