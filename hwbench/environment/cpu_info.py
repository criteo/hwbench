from __future__ import annotations
import pathlib

from ..utils.external import External


class CPU_INFO(External):
    def run_cmd(self) -> list[str]:
        """Raw cpu information"""
        return ["lscpu"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        self.cpu_specs = {}
        for line in stdout.decode("utf-8").splitlines():
            if not line:
                continue
            item, value = line.split(":", 1)
            if item == "Flags":
                flags = []
                for flag in value.split():
                    flags.append(flag)
                    self.cpu_specs[item.strip()] = flags
            else:
                self.cpu_specs[item.strip()] = value.strip()
        return self.cpu_specs

    def run_cmd_version(self) -> list[str]:
        return ["lscpu", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        """Return the version of lscpu"""
        return stdout.split()[3]

    @property
    def name(self) -> str:
        return "lscpu"

    def __init__(self, out_dir: pathlib.Path):
        super().__init__(out_dir)
        self.cpu_specs = {}

    def get_specs(self) -> dict[str, str]:
        return self.cpu_specs

    def get_arch(self) -> str:
        return self.get_specs().get("Architecture")

    def get_family(self) -> int:
        return int(self.get_specs().get("CPU family"))

    def get_max_freq(self) -> float:
        max_freq = self.get_specs().get("CPU max MHz")
        if not max_freq:
            max_freq = 0
        return float(max_freq)

    def get_model(self) -> int:
        return int(self.get_specs().get("Model"))

    def get_model_name(self) -> str:
        return self.get_specs().get("Model name")

    def get_stepping(self) -> int:
        return int(self.get_specs().get("Stepping"))

    def get_vendor(self) -> str:
        return self.get_specs().get("Vendor ID")
