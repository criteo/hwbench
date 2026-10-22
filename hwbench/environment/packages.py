import re

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


class DpkgList(External):
    """The packages installed by apt, from the dpkg database it relies on."""

    def run_cmd(self) -> list[str]:
        return ["dpkg-query", "-W", "-f", "${Package} ${Version} ${Architecture}\n"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return sorted(iter(stdout.decode("utf-8").splitlines()))

    def run_cmd_version(self) -> list[str]:
        return ["dpkg-query", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        # Debian dpkg-query package management program version 1.22.6 (amd64).
        match = re.search(rb"version (\S+)", stdout)
        self.version = match.group(1).decode() if match else ""
        return self.version

    @property
    def name(self) -> str:
        return "dpkg-list"


# The package managers whose installed packages are listed, when their binary is present
PACKAGE_LISTS = [RpmList, DpkgList]
