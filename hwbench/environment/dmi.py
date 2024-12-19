from __future__ import annotations
import os
import pathlib
from typing import Optional

from ..utils.archive import create_tar_from_directory, extract_file_from_tar
from ..utils.external import External


class DmiSys:
    SYS_DMI = "/sys/devices/virtual/dmi/id/"
    ARCH_DMI = "dmi-info.tar"

    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.tarfilename = self.out_dir.joinpath(self.ARCH_DMI)
        create_tar_from_directory(self.SYS_DMI, pathlib.Path(self.tarfilename.as_posix()))

    @staticmethod
    def bytes_to_dmi_info(payload: Optional[bytes]) -> Optional[str]:
        if payload is None:
            return None
        return payload.decode("utf-8", "strict").replace("\n", "")

    @staticmethod
    def extract_dmi_payload(tarfile: pathlib.Path, file: str, root_path=SYS_DMI) -> Optional[bytes]:
        return extract_file_from_tar(tarfile.as_posix(), os.path.join(root_path, file))

    def info(self, name: str) -> Optional[str]:
        return self.bytes_to_dmi_info(self.extract_dmi_payload(self.tarfilename, name))

    def dump(self) -> dict[str, Optional[str | int] | dict]:
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
            },
            "sysconf_threads": os.sysconf("SC_NPROCESSORS_ONLN"),
        }


class DmidecodeRaw(External):
    def run_cmd(self) -> list[str]:
        """Raw dmi information to be passed to dmidecode --from-dump"""
        return ["dmidecode", "--dump-bin", str(self.out_dir.joinpath("dmidecode.bin"))]

    def parse_cmd(self, _stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["dmidecode", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        """Not much to parse since the full output is the version with dmidecode"""
        return stdout.strip()

    @property
    def name(self) -> str:
        return "dmidecode-bin"
