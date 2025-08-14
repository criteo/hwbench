from hwbench.utils.external import External


class RpmList(External):
    def run_cmd(self) -> list[str]:
        return ["rpm", "-qa"]

    # TODO: better parsing of package, version, architecture
    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return sorted(iter(stdout.decode("utf-8").splitlines()))

    def run_cmd_version(self) -> list[str]:
        return ["rpm", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = stdout.split()[2].decode()
        return self.version

    @property
    def name(self) -> str:
        return "rpm-list"
