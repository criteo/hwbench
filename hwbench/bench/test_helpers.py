import unittest
from . import benchmarks
from . import test_benchmarks_common as tbc
from ..config import config


class TestHelpers(unittest.TestCase):
    def test_helpers(self):
        """Testing helper functions."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        def bench_name(index) -> str:
            """Return the benchmark name"""
            return get_bench_parameters(index).get_name()

        hw = tbc.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        cfg = config.Config("./config/helpers.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        benches.parse_config()

        # Simple
        ## On a simple test and for a 64 core cpu, we must have 8 jobs created
        ## Each of them must have the number of logical cores listed below
        logical_cores = [2, 4, 6, 8, 16, 32, 64, 96, 128]
        for job in range(0, 9):
            assert bench_name(job) == "simple"
            assert len(get_bench_parameters(job).get_pinned_cpu()) == logical_cores[job]
