import unittest
from . import benchmarks
from . import test_benchmarks_common as tbc
from ..config import config


class TestCores(unittest.TestCase):
    def test_cores(self):
        """Check cores syntax."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        hw = tbc.load_mocked_hardware(cpucores="./tests/parsing/cpu_cores/v2321")

        cfg = config.Config("./config/cores.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        benches.parse_config()
        CPU0 = [0, 64]
        CPU1 = [1, 65]
        CPU0_1 = sorted(CPU0 + CPU1)
        CPU0_7 = [0, 1, 2, 3, 4, 5, 6, 7, 64, 65, 66, 67, 68, 69, 70, 71]
        assert cfg.get_hosting_cpu_cores("cores") == [CPU0, CPU1, CPU0_7, CPU0_1]
        assert get_bench_parameters(0).get_pinned_cpu() == CPU0
        assert get_bench_parameters(1).get_pinned_cpu() == CPU1
        assert get_bench_parameters(2).get_pinned_cpu() == CPU0_7
        assert get_bench_parameters(3).get_pinned_cpu() == CPU0_1

        # Testing broken syntax that must fail
        cfg = config.Config("./config/sample_weirds.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        with self.assertRaises(SystemExit):
            cfg.get_hosting_cpu_cores("invalid_cpu_core")
            cfg.get_hosting_cpu_cores("alpha_cpu_core")
