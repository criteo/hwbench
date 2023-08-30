from __future__ import annotations
import pathlib
import re

from ..utils.external import External


class NUMA(External):
    def run_cmd(self) -> list[str]:
        """Raw NUMA information"""
        return ["numactl", "-H"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for line in stdout.decode("utf-8").split("\n"):
            if not line:
                continue
            # node 0 cpus: 0 1 2 3 4 5 6 7 32 33 34 35 36 37 38 39
            match = re.search(r"node (?P<node>[0-9]+) cpus: (?P<cpus>.*)", line)
            if match:
                self.numa_domains[int(match.group("node"))] = [
                    int(cpu) for cpu in match.group("cpus").split()
                ]
        return self.numa_domains

    def run_cmd_version(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return b""

    @property
    def name(self) -> str:
        return "numactl"

    def __init__(self, out_dir: pathlib.Path):
        super().__init__(out_dir)
        self.numa_domains = {}

    def count(self) -> int:
        return len(self.numa_domains)

    def get_cores(self, numa_domain) -> list[int]:
        return self.numa_domains.get(numa_domain, [])
