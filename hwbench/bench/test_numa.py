from . import test_benchmarks_common as tbc


class TestNuma(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.NUMA0 = list(range(0, 8)) + list(range(64, 72))
        self.NUMA1 = list(range(8, 16)) + list(range(72, 80))
        self.NUMA0_1 = sorted(self.NUMA0 + self.NUMA1)
        self.NUMA7 = list(range(56, 64)) + list(range(120, 128))
        self.NUMA07 = list(range(0, self.hw.get_cpu().get_logical_cores_count()))
        self.load_benches("./hwbench/config/numa.conf")
        self.parse_jobs_config()

    def test_quadrant(self):
        """Check quadrant syntax."""
        # Each quadrant is made of two numa nodes on this AMD system
        assert self.hw.get_cpu().get_cores_in_quadrant(0) == self.NUMA0_1
        assert self.get_bench_parameters(5).get_pinned_cpu() == self.NUMA0_1
        assert len(self.get_bench_parameters(6).get_pinned_cpu()) == 32
        assert len(self.get_bench_parameters(7).get_pinned_cpu()) == 128
        assert len(self.get_bench_parameters(8).get_pinned_cpu()) == 64

        # Testing broken syntax that must fail
        # Testing quadrants
        self.load_benches("./hwbench/config/sample_weirds.conf")
        for test_name in [
            "invalid_quadrant",
            "alpha_quadrant",
        ]:
            self.should_be_fatal(self.get_jobs_config().get_hosting_cpu_cores, test_name)

    def test_numa(self):
        """Check numa syntax"""
        assert self.hw.logical_core_count() == 128
        assert self.hw.get_cpu().get_vendor() == "AuthenticAMD"
        assert self.hw.get_cpu().get_numa_domains_count() == 8
        assert self.hw.get_cpu().get_quadrants_count() == 4
        assert self.get_jobs_config().get_hosting_cpu_cores("numa_nodes") == [
            self.NUMA0,
            self.NUMA1,
            self.NUMA7,
            self.NUMA07,
            self.NUMA0_1,
        ]

        assert self.get_bench_parameters(0).get_pinned_cpu() == self.NUMA0
        assert self.get_bench_parameters(1).get_pinned_cpu() == self.NUMA1
        assert self.get_bench_parameters(2).get_pinned_cpu() == self.NUMA7
        assert self.get_bench_parameters(3).get_pinned_cpu() == self.NUMA07
        assert self.get_bench_parameters(4).get_pinned_cpu() == self.NUMA0_1

        # Testing broken syntax that must fail
        # Testing quadrants
        self.load_benches("./hwbench/config/sample_weirds.conf")
        for test_name in [
            "invalid_numa_nodes",
            "alpha_numa_nodes",
        ]:
            self.should_be_fatal(self.get_jobs_config().get_hosting_cpu_cores, test_name)
