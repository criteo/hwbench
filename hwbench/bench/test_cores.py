from . import test_benchmarks_common as tbc


class TestCores(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./config/cores.conf")
        self.parse_config()

    def test_cores(self):
        """Check cores syntax."""
        CPU0 = [0, 64]
        CPU1 = [1, 65]
        CPU0_1 = sorted(CPU0 + CPU1)
        CPU0_7 = [0, 1, 2, 3, 4, 5, 6, 7, 64, 65, 66, 67, 68, 69, 70, 71]
        assert self.get_config().get_hosting_cpu_cores("cores") == [
            CPU0,
            CPU1,
            CPU0_7,
            CPU0_1,
        ]
        assert self.get_bench_parameters(0).get_pinned_cpu() == CPU0
        assert self.get_bench_parameters(1).get_pinned_cpu() == CPU1
        assert self.get_bench_parameters(2).get_pinned_cpu() == CPU0_7
        assert self.get_bench_parameters(3).get_pinned_cpu() == CPU0_1

        # Testing broken syntax that must fail
        self.load_benches("./config/sample_weirds.conf")
        with self.assertRaises(SystemExit):
            self.get_config().get_hosting_cpu_cores("invalid_cpu_core")
            self.get_config().get_hosting_cpu_cores("alpha_cpu_core")
