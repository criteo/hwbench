import pathlib
from typing import Optional

from ..utils.external import External


class CPU_CORES(External):
    def run_cmd(self) -> list[str]:
        """Raw cpu information"""
        return ["lscpu", "--all", "-pSOCKET,CORE,CPU"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for line in stdout.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            socket, core, cpu = line.strip().split(",", 2)
            self.get_cores(int(socket), int(core)).append(int(cpu))

        return self.sockets

    def run_cmd_version(self) -> list[str]:
        return ["lscpu", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        """Return the version of lscpu"""
        return stdout.split()[3]

    @property
    def name(self) -> str:
        return "lscpu_cores"

    def __init__(self, out_dir: pathlib.Path):
        self.raw_core_list = None
        self.raw_cpu_config = None
        self.sockets: dict[int, dict[int, list[int]]] = {}
        self.logical_cpu: dict[int, list[int]] = {}
        super().__init__(out_dir)

    def get_socket(self, number) -> dict[int, list[int]]:
        if not self.sockets.get(number):
            self.sockets[number] = {}
        return self.sockets[number]

    def get_cores(self, socket, number) -> list[int]:
        if not self.get_socket(socket).get(number):
            self.sockets[socket][number] = []
        return self.get_socket(socket)[number]

    def get_physical_cores(self) -> list[int]:
        """Return the list of physical cores."""
        cores = []
        for socket in self.sockets:
            cores += [key for key in self.get_socket(socket).keys()]
        return cores

    def get_hyperthread_cores(self) -> list[int]:
        """Return the list of hyperthread cores."""
        cores = []
        for socket in self.sockets:
            for core in self.get_socket(socket):
                cores += [c for c in self.get_cores(socket, core) if c != int(core)]
        return cores

    def get_physical_cores_count(self) -> int:
        """Return the number of physical cpu core we detected."""
        return len(self.get_physical_cores())

    def get_logical_cores_count(self) -> int:
        """Return the number of logical cpu core we detected."""
        return len(self.get_physical_cores()) + len(self.get_hyperthread_cores())

    def get_peer_siblings(self, logical_cpu) -> list[int]:
        """Return the list of logical cores running on the same physical core."""
        # Let's find the associated core/ht of a given logical_cpu
        for socket in self.sockets:
            for core in self.get_socket(socket):
                if logical_cpu in self.get_cores(socket, core):
                    return self.get_cores(socket, core)
        return []

    def get_peer_sibling(self, logical_cpu) -> Optional[int]:
        """Return sibling of a logical core."""
        # Let's find the associated core/ht of a given logical_cpu
        for core in self.get_peer_siblings(logical_cpu):
            if core != logical_cpu:
                return core

        return None
