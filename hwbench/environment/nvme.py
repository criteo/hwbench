from hwbench.utils.external import External


class Nvme(External):
    def run_cmd(self) -> list[str]:
        """Dump verbose decoded nvme-cli info"""
        return ["nvme", "list", "-v", "-ojson"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["nvme", "version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = stdout.split()[2].decode()
        return self.version

    @property
    def name(self) -> str:
        return "nvme-cli"
