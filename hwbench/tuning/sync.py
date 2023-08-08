from ..utils.external import External


class Sync(External):
    @property
    def name(self) -> str:
        return "sync"

    def run_cmd_version(self) -> list[str]:
        return [
            "sync",
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return ["sync"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return stdout.split()[3]

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return None
