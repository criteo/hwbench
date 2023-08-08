from ..utils.external import External


class Sync(External):
    @property
    def name(self):
        return "sync"

    def run_cmd_version(self):
        return [
            "sync",
            "--version",
        ]

    def run_cmd(self):
        return ["sync"]

    def parse_version(self, stdout, _stderr):
        return stdout.split()[3]

    def parse_cmd(self, stdout, stderr):
        return None
