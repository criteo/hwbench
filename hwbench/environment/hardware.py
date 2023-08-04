import os
import pathlib
from typing import Optional

from hwbench.archive.archive import create_tar_from_directory, extract_file_from_tar


class Hardware:
    SYS_DMI = "/sys/devices/virtual/dmi/id/"
    ARCH_DMI = "dmi-info.tar"

    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir

    @staticmethod
    def bytes_to_dmi_info(payload: Optional[bytes]) -> Optional[str]:
        if payload is None:
            return None
        return payload.decode("utf-8", "strict").replace("\n", "")

    @staticmethod
    def extract_dmi_payload(
        tarfile: pathlib.Path, file: str, root_path=SYS_DMI
    ) -> Optional[bytes]:
        return extract_file_from_tar(tarfile.as_posix(), os.path.join(root_path, file))

    def dump(self) -> dict[str, Optional[str]]:
        tarfilename = self.out_dir.joinpath(self.ARCH_DMI)
        create_tar_from_directory(self.SYS_DMI, tarfilename.as_posix())

        return {
            # TODO: more, or even dmidecode parsing
            "vendor": self.bytes_to_dmi_info(
                self.extract_dmi_payload(tarfilename, "sys_vendor")
            ),
            "product": self.bytes_to_dmi_info(
                self.extract_dmi_payload(tarfilename, "product_name")
            ),
            "serial": self.bytes_to_dmi_info(
                self.extract_dmi_payload(tarfilename, "product_serial")
            ),
            "bios": {
                "version": self.bytes_to_dmi_info(
                    self.extract_dmi_payload(tarfilename, "bios_version")
                ),
                "release": self.bytes_to_dmi_info(
                    self.extract_dmi_payload(tarfilename, "bios_release")
                ),
            },
            "sysconf_threads": os.sysconf("SC_NPROCESSORS_ONLN"),
        }
