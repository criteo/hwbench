from __future__ import annotations

import pathlib

from hwbench.environment.dmi import DUMP_TABLE_OFFSET, heights

VENDORS = pathlib.Path(__file__).parent / "tests" / "vendors"


def structure(kind: int, formatted: bytes, strings: list[bytes]) -> bytes:
    """An SMBIOS structure: its header, the rest of its formatted area and its strings, ending with two nulls."""
    area = bytes([kind, 4 + len(formatted)]) + b"\x00\x00" + formatted
    return area + (b"".join(string + b"\x00" for string in strings) + b"\x00" if strings else b"\x00\x00")


def dump(*structures: bytes) -> bytes:
    """A dump of dmidecode --dump-bin: an entry point, then the table."""
    return b"_SM3_".ljust(DUMP_TABLE_OFFSET, b"\x00") + b"".join(structures) + structure(127, b"", [])


def system(serial: bytes) -> bytes:
    # Manufacturer, product, version, then the serial at 0x07
    return structure(1, bytes([1, 2, 0, 3]), [b"Dell Inc.", b"PowerEdge C6615", serial])


def chassis(height: int, serial: bytes = b"CHASSIS") -> bytes:
    # The formatted area after the header: manufacturer, type, version, serial, asset tag, the states,
    # the security status and the OEM information (0x04 to 0x10), then the height at 0x11
    return structure(3, bytes([1, 0x17, 0, 2, 0, 3, 3, 3, 3]) + bytes(4) + bytes([height, 2]), [b"Dell Inc.", serial])


def test_heights():
    node = system(b"NODE")
    # After a structure with strings, a server alone: a chassis of its serial
    assert heights(dump(node, chassis(2, b"NODE"))) == (2, 2)
    # A chassis of another serial holds the server, of 1U by default: a Dell C6600
    assert heights(dump(node, chassis(2))) == (1, 2)
    # Both, in any order: an HPE Apollo
    assert heights(dump(node, chassis(1, b"NODE"), chassis(2))) == (1, 2)
    assert heights(dump(node, chassis(2), chassis(1, b"NODE"))) == (1, 2)
    # Not specified, without a chassis or without a system
    assert heights(dump(node, chassis(0, b"NODE"), chassis(0))) == (1, 1)
    assert heights(dump(node, chassis(0, b"NODE"), chassis(2))) == (1, 2)
    assert heights(dump(node)) == (1, 1)
    assert heights(dump(chassis(2, b"NODE"))) == (1, 1)
    # An SMBIOS older than 2.3, whose chassis stops before its height
    assert heights(dump(node, structure(3, bytes([1, 0x17, 0, 2]), [b"HPE", b"NODE"]))) == (1, 1)
    assert heights(b"") == (1, 1)


def test_heights_apollo():
    # A node of an HPE Apollo 2000 (XL225n Gen10 Plus), anonymized: a chassis of 1U of the serial of the node,
    # then the enclosure of 2U of the 4 nodes
    assert heights((VENDORS / "Hpe" / "XL225N" / "dmidecode.bin").read_bytes()) == (1, 2)
