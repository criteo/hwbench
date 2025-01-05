from hwbench.utils.external import External


class Lspci(External):
    def run_cmd(self) -> list[str]:
        """Dump verbose decoded lspci info"""
        return ["lspci", "-vvv"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["lspci", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[2]
        return self.version

    @property
    def name(self) -> str:
        return "lspci-verbose"


class LspciBin(Lspci):
    def run_cmd(self) -> list[str]:
        """Dump raw lspci info to be interpreted with lspci -F <file>"""
        return ["lspci", "-xxxx"]

    @property
    def name(self) -> str:
        return "lspci-bin"
