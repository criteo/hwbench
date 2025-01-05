import re

from hwbench.utils.external import External


class Ami_Aptio(External):
    def run_cmd(self) -> list[str]:
        return [
            "EtaSceLnx64",
            "/o",
            "/lang",
            "/s",
            str(self.out_dir.joinpath("bios-config")),
        ]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return stdout.decode("utf-8")

    def run_cmd_version(self) -> list[str]:
        return ["EtaSceLnx64"]

    def parse_version(self, _stdout: bytes, stderr: bytes) -> bytes:
        self.version = b""
        for line in stderr.decode("utf-8").splitlines():
            if not line:
                continue
            # |                   AMISCE Utility. Ver 5.05.05.0006.2301             |
            match = re.search(r".*AMISCE Utility. Ver (?P<version>[0-9.]+).*$", line)
            if match:
                self.version = bytes(match.group("version"), encoding="utf-8")
                break
        return self.version

    @property
    def name(self) -> str:
        return "ami-aptio-bios"
