from ..utils.external import External


class RpmList(External):
    def run_cmd(self):
        return ["rpm", "-qa"]

    # TODO: better parsing of package, version, architecture
    def parse_cmd(self, stdout, _stderr):
        return stdout

    def run_cmd_version(self):
        return ["rpm", "--version"]

    def parse_version(self, stdout, _stderr):
        self.version = stdout.split()[2]
        return self.version

    @property
    def name(self):
        return "rpm-list"
