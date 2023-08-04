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

    def run(self):
        ver = subprocess.run(
            self.run_cmd_version(),
            capture_output=True,
        )
        open(f"{self.out_dir}/{self.name}-version-stdout", "wb").write(ver.stdout)
        open(f"{self.out_dir}/{self.name}-version-stderr", "wb").write(ver.stderr)
        self.parse_version(ver.stdout, ver.stderr)

        out = subprocess.run(
            self.run_cmd(),
            capture_output=True,
        )
        # save outputs

        open(f"{self.out_dir}/{self.name}-stdout", "wb").write(out.stdout)
        open(f"{self.out_dir}/{self.name}-stderr", "wb").write(out.stderr)

        return self.parse_cmd(out.stdout, out.stderr)
