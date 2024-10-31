import pathlib

from ..utils.external import External


class CPU_INFO(External):
    def run_cmd(self) -> list[str]:
        """Raw cpu information"""
        return ["lscpu"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for line in stdout.decode("utf-8").splitlines():
            if not line:
                continue
            item, value = line.split(":", 1)
            if item == "Flags":
                for flag in value.split():
                    self.flags.append(flag)
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
        self.cpu_specs: dict[str, str] = {}
        self.flags: list[str] = []

    def get_specs(self) -> dict[str, str]:
        return self.cpu_specs

    def _mandatory_spec(self, name) -> str:
        m = self.get_specs().get(name)
        if not m:
            raise ValueError(f"Missing cpu spec {name}")
        return m

    def get_arch(self) -> str:
        return self._mandatory_spec("Architecture")

    def get_family(self) -> int:
        return int(self._mandatory_spec("CPU family"))

    def get_max_freq(self) -> float:
        max_freq = self.get_specs().get("CPU max MHz")
        if not max_freq:
            max_freq = "0"
        return float(max_freq)

    def get_model(self) -> int:
        return int(self._mandatory_spec("Model"))

    def get_model_name(self) -> str:
        try:
            return self._mandatory_spec("Model name")
        except ValueError as _:
            return self._mandatory_spec("BIOS Model name")

    def get_stepping(self) -> int:
        return int(self._mandatory_spec("Stepping"))

    def get_vendor(self) -> str:
        return self._mandatory_spec("Vendor ID")

    def get_flags(self) -> list[str]:
        return self.flags

    def get_sockets_count(self) -> int:
        return int(self._mandatory_spec("Socket(s)"))
