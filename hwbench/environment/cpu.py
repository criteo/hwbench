from typing import Optional

from .cpu_info import CPU_INFO
from .cpu_cores import CPU_CORES
from .numa import NUMA


class CPU:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.cpu_info = CPU_INFO(self.out_dir)
        self.cpu_cores = CPU_CORES(self.out_dir)
        self.numa = NUMA(self.out_dir)

    def detect(self):
        self.cpu_info.run()
        self.cpu_cores.run()
        self.numa.run()

    def get_arch(self) -> str:
        return self.cpu_info.get_arch()

    def get_family(self) -> int:
        return self.cpu_info.get_family()

    def get_max_freq(self) -> float:
        return self.cpu_info.get_max_freq()

    def get_model(self) -> int:
        return self.cpu_info.get_model()

    def get_model_name(self) -> str:
        return self.cpu_info.get_model_name()

    def get_stepping(self) -> int:
        return self.cpu_info.get_stepping()

    def get_vendor(self) -> str:
        return self.cpu_info.get_vendor()

    def get_physical_cores_count(self) -> int:
        """Return the number of physical cpu core we detected."""
        return self.cpu_cores.get_physical_cores_count()

    def get_logical_cores_count(self) -> int:
        """Return the number of logical cpu core we detected."""
        return self.cpu_cores.get_logical_cores_count()

    def get_peer_siblings(self, logical_cpu) -> list[int]:
        """Return the list of logical cores running on the same physical core."""
        return self.cpu_cores.get_peer_siblings(logical_cpu)

    def get_peer_sibling(self, logical_cpu) -> Optional[int]:
        """Return sibling of a logical core."""
        return self.cpu_cores.get_peer_sibling(logical_cpu)

    def get_hyperthread_cores(self) -> list[int]:
        """Return the list of hyperthread cores."""
        return self.cpu_cores.get_hyperthread_cores()

    def get_physical_cores(self) -> list[int]:
        """Return the list of physical cores."""
        return self.cpu_cores.get_physical_cores()

    def get_numa_domains_count(self) -> int:
        """Return the number of numa domains."""
        return self.numa.count()

    def get_logical_cores_in_numa_domain(self, numa_domain) -> list[int]:
        """Return logical cores in a numa domain."""
        return self.numa.get_cores(numa_domain)

    def dump(self):
        return {
            "vendor": self.get_vendor(),
            "model": self.get_model_name(),
            "logical_cores": self.get_logical_cores_count(),
            "physical_cores": self.get_physical_cores_count(),
            "numa_domains": self.get_numa_domains_count(),
        }

    def get_flags(self) -> list[str]:
        return self.cpu_info.get_flags()
