import json

from ....utils.external import External


class Ilorest(External):
    def run_cmd(self) -> list[str]:
        return ["ilorest", "get", "--json", "--nologo", "--select", "Bios."]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return json.loads(stdout.decode("utf-8"))

    def run_cmd_version(self) -> list[str]:
        return ["ilorest", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    @property
    def name(self) -> str:
        return "ilorest-bios"


class IlorestServerclone(External):
    def run_cmd(self) -> list[str]:
        """This creates a file named ilorest_clone.json in the output directory"""
        return ["ilorest", "serverclone", "save", "--nologo", "--auto"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["ilorest", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    @property
    def name(self) -> str:
        return "ilorest-serverclone"
