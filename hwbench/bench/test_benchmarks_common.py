import pathlib
import unittest
from . import benchmarks
from ..config import config
from ..environment.cpu import MockCPU
from ..environment.cpu_info import CPU_INFO
from ..environment.cpu_cores import CPU_CORES
from ..environment.numa import NUMA
from ..environment.mock import MockHardware


class TestCommon(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def load_mocked_hardware(
        self,
        cpuinfo=None,
        cpucores=None,
        numa=None,
    ):
        """Create a fake hardware context"""

        def load(target, path):
            instance = target(path)
            stdout = (path / "stdout").read_bytes()
            stderr = (path / "stderr").read_bytes()
            instance.parse_cmd(stdout, stderr)
            return instance

        fake_numa = None
        if numa:
            fake_numa = load(NUMA, pathlib.Path(numa))

        fake_cpuinfo = None
        if cpuinfo:
            fake_cpuinfo = load(CPU_INFO, pathlib.Path(cpuinfo))

        fake_cpucores = None
        if cpucores:
            fake_cpucores = load(CPU_CORES, pathlib.Path(cpucores))

        cpu = MockCPU(".", fake_cpuinfo, fake_cpucores, fake_numa)
        self.hw = MockHardware(cpu=cpu)

    def load_benches(self, config_file: str):
        """Turn config_file into benchmarks"""
        self.config = config.Config(config_file, self.hw)
        self.benches = benchmarks.Benchmarks(".", self.config, self.hw)

    def get_bench_parameters(self, index):
        """Return the benchmark parameters."""
        return self.benches.get_benchmarks()[index].get_parameters()

    def get_benches(self):
        return self.benches

    def parse_config(self):
        return self.benches.parse_config()

    def get_config(self) -> config.Config:
        return self.config

    def bench_name(self, index) -> str:
        """Return the benchmark name"""
        return self.get_bench_parameters(index).get_name()

    def bench_em(self, index) -> str:
        """Return the benchmark engine module name"""
        return self.benches.get_benchmarks()[index].get_enginemodule().get_name()

    def bench_emp(self, index) -> str:
        """Return the benchmark engine module parameter"""
        return self.get_bench_parameters(index).get_engine_module_parameter()
