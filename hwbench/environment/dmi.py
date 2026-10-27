from __future__ import annotations

import os
import pathlib

from hwbench.utils.archive import create_tar_from_directory, extract_file_from_tar
from hwbench.utils.external import External

# The raw SMBIOS tables written by dmidecode --dump-bin: its entry point, then the table at offset 32
DMIDECODE_BIN = "dmidecode.bin"
DUMP_TABLE_OFFSET = 32
# The SMBIOS structures read: the system and the chassis, with their serial at offset 0x07, the chassis with
# its height in rack units at offset 0x11 since SMBIOS 2.3, and the end of the table
SYSTEM_TYPE = 1
CHASSIS_TYPE = 3
SERIAL = 0x07
CHASSIS_HEIGHT = 0x11
END_OF_TABLE = 127


def smbios_structures(table: bytes):
    """The type, the formatted area and the strings of each structure of an SMBIOS table, up to its end."""
    offset = 0
    while offset + 4 <= len(table):
        kind, length = table[offset], table[offset + 1]
        if length < 4:
            return
        # The strings of a structure follow its formatted area, ending with two nulls
        end = table.find(b"\0\0", offset + length)
        if end < 0:
            return
        strings = table[offset + length : end].split(b"\0") if end > offset + length else []
        yield kind, table[offset : offset + length], strings
        if kind == END_OF_TABLE:
            return
        offset = end + 2


def smbios_string(structure: bytes, strings: list[bytes], offset: int) -> bytes | None:
    """The string of a structure its byte at offset refers to, from 1; None for 0 or past its end."""
    index = structure[offset] if len(structure) > offset else 0
    return strings[index - 1].strip() if 0 < index <= len(strings) else None


def heights(dump: bytes) -> tuple[int, int]:
    """The heights in rack units of the server and of its chassis, from a dmidecode --dump-bin. The server
    has the one of the chassis of its serial, 1 otherwise. Its chassis is the one of another serial holding
    it, like the enclosure of 2U of the nodes of 1U of an HPE Apollo 2000, giving both, or of a Dell C6600,
    giving only its own; the server alone otherwise, as a DL365 of 1U giving a single chassis of its serial."""
    system = None
    chassis: list[tuple[bytes | None, int]] = []
    for kind, structure, strings in smbios_structures(dump[DUMP_TABLE_OFFSET:]):
        if kind == SYSTEM_TYPE:
            system = smbios_string(structure, strings, SERIAL)
        elif kind == CHASSIS_TYPE and len(structure) > CHASSIS_HEIGHT:
            chassis.append((smbios_string(structure, strings, SERIAL), structure[CHASSIS_HEIGHT]))
    # A height of 0 is not specified
    server = next((height for serial, height in chassis if system and serial == system and height), 1)
    enclosure = next((height for serial, height in chassis if system and serial != system and height), server)
    return server, enclosure


class DmiSys:
    SYS_DMI = "/sys/devices/virtual/dmi/id/"
    ARCH_DMI = "dmi-info.tar"

    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.tarfilename = self.out_dir.joinpath(self.ARCH_DMI)
        create_tar_from_directory(self.SYS_DMI, pathlib.Path(self.tarfilename.as_posix()))

    @staticmethod
    def bytes_to_dmi_info(payload: bytes | None) -> str | None:
        if payload is None:
            return None
        return payload.decode("utf-8", "strict").replace("\n", "")

    @staticmethod
    def extract_dmi_payload(tarfile: pathlib.Path, file: str, root_path=SYS_DMI) -> bytes | None:
        return extract_file_from_tar(tarfile.as_posix(), os.path.join(root_path, file))

    def info(self, name: str) -> str | None:
        return self.bytes_to_dmi_info(self.extract_dmi_payload(self.tarfilename, name))

    def heights(self) -> tuple[int, int]:
        """The heights of the server and of its chassis, from the dump of dmidecode; 1 without it."""
        try:
            return heights(self.out_dir.joinpath(DMIDECODE_BIN).read_bytes())
        except OSError:
            return 1, 1

    def dump(self) -> dict[str, str | int | None | dict]:
        server_height, chassis_height = self.heights()
        return {
            "vendor": self.info("sys_vendor"),
            "product": self.info("product_name"),
            "serial": self.info("product_serial"),
            "bios": {
                "version": self.info("bios_version"),
                "release": self.info("bios_release"),
            },
            "chassis": {
                "product": self.info("chassis_version"),
                "serial": self.info("chassis_serial"),
                "height": chassis_height,
            },
            "height": server_height,
            "sysconf_threads": os.sysconf("SC_NPROCESSORS_ONLN"),
        }


class DmidecodeRaw(External):
    def run_cmd(self) -> list[str]:
        """Raw dmi information to be passed to dmidecode --from-dump"""
        return ["dmidecode", "--dump-bin", str(self.out_dir.joinpath(DMIDECODE_BIN))]

    def parse_cmd(self, _stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["dmidecode", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        """Not much to parse since the full output is the version with dmidecode"""
        return stdout.strip().decode()

    @property
    def name(self) -> str:
        return "dmidecode-bin"
