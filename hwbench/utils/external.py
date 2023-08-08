import pathlib
import subprocess
from abc import abstractmethod, ABC


class External(ABC):
    # TODO: class settings (timeout, type of test, number of jobs, etc.)
    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir

    @abstractmethod
    def run_cmd(self) -> list[str]:
        return []

    @abstractmethod
    def run_cmd_version(self) -> list[str]:
        return []

    @property
    @abstractmethod
    def name(self) -> str:
        return ""

    @abstractmethod
    def parse_cmd(self, stdout: bytes, stderr: bytes):
        """Returns a json-able type"""
        return {}

    @abstractmethod
    def parse_version(self, stdout: bytes, stderr: bytes) -> bytes:
        return b""

    def _write_output(self, name: str, content: bytes):
        if len(content) > 0:
            self.out_dir.joinpath(f"{self.name}-{name}").write_bytes(content)

    def run(self):
        """Returns the output of parse_cmd (a json-able type)"""
        ver = subprocess.run(
            self.run_cmd_version(),
            capture_output=True,
            cwd=self.out_dir,
        )
        self._write_output("version-stdout", ver.stdout)
        self._write_output("version-stderr", ver.stderr)
        self.parse_version(ver.stdout, ver.stderr)

        out = subprocess.run(
            self.run_cmd(),
            capture_output=True,
        )
        # save outputs

        self._write_output("stdout", out.stdout)
        self._write_output("stderr", out.stderr)

        return self.parse_cmd(out.stdout, out.stderr)
