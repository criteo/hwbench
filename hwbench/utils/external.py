import subprocess
from abc import abstractmethod, ABC


class External(ABC):
    # TODO: class settings (timeout, type of test, number of jobs, etc.)
    def __init__(self, out_dir):
        self.out_dir = out_dir

    @abstractmethod
    def run_cmd(self):
        return []

    @abstractmethod
    def run_cmd_version(self):
        return []

    @property
    @abstractmethod
    def name(self):
        return ""

    @abstractmethod
    def parse_cmd(self, stdout, stderr):
        return {}

    @abstractmethod
    def parse_version(self, stdout, stderr):
        return {}

    def _write_output(self, name, content):
        if len(content) > 0:
            self.out_dir.joinpath(f"{self.name}-{name}").write_bytes(content)

    def run(self):
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
