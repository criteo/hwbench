from . import test_benchmarks_common as tbc


class TestCores(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/cores.conf")
        self.parse_jobs_config()

    def test_cores(self):
        """Check cores syntax."""
        CPU0 = [0, 64]
        CPU1 = [1, 65]
        CPU0_1 = sorted(CPU0 + CPU1)
        CPU0_7 = list(range(0, 8)) + list(range(64, 72))
        assert self.get_jobs_config().get_hosting_cpu_cores("cores") == [
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
        self.load_benches("./hwbench/config/sample_weirds.conf")
        for test_name in [
            "invalid_cpu_core",
            "alpha_cpu_core",
        ]:
            self.should_be_fatal(self.get_jobs_config().get_hosting_cpu_cores, test_name)
