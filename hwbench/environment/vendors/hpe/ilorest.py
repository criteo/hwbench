import json

from ....utils.external import External


class Ilorest(External):
    def run_cmd(self):
        return ["ilorest", "get", "--json", "--nologo", "--select", "Bios."]

    # TODO: better parsing of package, version, architecture
    def parse_cmd(self, stdout, _stderr):
        return json.loads(stdout.decode("utf-8"))

    def run_cmd_version(self):
        return ["ilorest", "--version"]

    def parse_version(self, stdout, _stderr):
        self.version = stdout.split()[3]
        return self.version

    @property
    def name(self):
        return "ilorest-bios"
