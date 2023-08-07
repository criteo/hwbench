from ..utils.external import External


class Lspci(External):
    def run_cmd(self):
        """Dump verbose decoded lspci info"""
        return ["lspci", "-vvv"]

    def parse_cmd(self, stdout, _stderr):
        return stdout

    def run_cmd_version(self):
        return ["lspci", "--version"]

    def parse_version(self, stdout, _stderr):
        self.version = stdout.split()[2]
        return self.version

    @property
    def name(self):
        return "lspci-verbose"


class LspciBin(Lspci):
    def run_cmd(self):
        """Dump raw lspci info to be interpreted with lspci -F <file>"""
        return ["lspci", "-xxxx"]

    @property
    def name(self):
        return "lspci-bin"
