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
                self.numa_domains[int(match.group("node"))] = [int(cpu) for cpu in match.group("cpus").split()]
            # node   0   1   2   3   4   5   6   7
            #  0:  10  11  12  12  12  12  12  12
            #  1:  11  10  12  12  12  12  12  12
            #  2:  12  12  10  11  12  12  12  12
            #  3:  12  12  11  10  12  12  12  12
            #  4:  12  12  12  12  10  11  12  12
            #  5:  12  12  12  12  11  10  12  12
            #  6:  12  12  12  12  12  12  10  11
            #  7:  12  12  12  12  12  12  11  10
            numa_distance = re.findall(r"(\d+): (.*)", line)
            if numa_distance:
                for source, latencies in numa_distance:
                    quadrant = self.__is_numa_node_in_quadrant(source)
                    numa_dest = -1
                    for latency in latencies.split():
                        numa_dest += 1
                        if int(latency) < 12:
                            if not self.__is_numa_node_in_quadrant(numa_dest):
                                if not quadrant:
                                    self.quadrants.append([])
                                    quadrant = self.quadrants[-1]
                                quadrant.append(int(numa_dest))
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
        self.numa_domains: dict[int, list[int]] = {}
        self.quadrants: list[list[int]] = []

    def count(self) -> int:
        return len(self.numa_domains)

    def get_cores(self, numa_domain) -> list[int]:
        return self.numa_domains.get(numa_domain, [])

    def quadrants_count(self) -> int:
        return len(self.quadrants)

    def get_numa_nodes_in_quadrant(self, quadrant: int) -> list[int]:
        if quadrant > len(self.quadrants) - 1:
            return []
        return self.quadrants[quadrant]

    def __is_numa_node_in_quadrant(self, numa_node: int) -> list[int]:
        for quadrant in self.quadrants:
            if numa_node in quadrant:
                return quadrant
        return []
