import os
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
        english_env = os.environ.copy()
        english_env["LC_ALL"] = "C"
        if self.run_cmd_version():
            ver = subprocess.run(
                self.run_cmd_version(),
                capture_output=True,
                cwd=self.out_dir,
                env=english_env,
            )
            self._write_output("version-stdout", ver.stdout)
            self._write_output("version-stderr", ver.stderr)
            self.parse_version(ver.stdout, ver.stderr)

        out = subprocess.run(
            self.run_cmd(),
            capture_output=True,
            env=english_env,
        )
        # save outputs

        self._write_output("stdout", out.stdout)
        self._write_output("stderr", out.stderr)

        return self.parse_cmd(out.stdout, out.stderr)


class External_Simple(External):
    # A simple implementation of External to immediately execute a command list
    def __init__(self, out_dir: pathlib.Path, cmd_list: list[str], cmd_name=None):
        self.cmd_list = cmd_list
        # Optional command name can be used if the same command has to be run twice.
        self.cmd_name = cmd_name
        super().__init__(out_dir)
        self.run()

    @property
    def name(self) -> str:
        if not self.cmd_name:
            return self.cmd_list[0]
        return self.cmd_name

    def run_cmd(self) -> list[str]:
        return self.cmd_list

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return bytes()

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}

    def run_cmd_version(self) -> list[str]:
        return []
