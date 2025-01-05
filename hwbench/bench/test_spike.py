from . import test_benchmarks_common as tbc


class TestSpike(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/spike.conf")
        self.parse_jobs_config()
        self.QUADRANT0 = list(range(0, 16)) + list(range(64, 80))
        self.QUADRANT1 = list(range(16, 32)) + list(range(80, 96))
        self.ALL = list(range(0, 128))

    def test_spike(self):
        """Check spike syntax."""
        assert self.benches.count_benchmarks() == 5
        assert self.benches.count_jobs() == 3
        assert self.benches.runtime() == 300
        assert self.benches.benchs[0].validate_parameters() is None

        assert self.get_bench_parameters(1).get_pinned_cpu() == self.QUADRANT0
        assert self.get_bench_parameters(2).get_pinned_cpu() == self.QUADRANT1
        assert self.get_bench_parameters(3).get_pinned_cpu() == self.ALL

        # Test the sync_start value
        assert self.get_bench_parameters(1).get_sync_start() == "none"
        assert self.get_bench_parameters(4).get_sync_start() == "time"

    def test_spike_wrong_syntax(self):
        # Testing broken syntax that must fail
        # Testing quadrants
        self.load_benches("./hwbench/config/spike_weirds.conf")
        self.parse_jobs_config(validate_parameters=False)

        self.should_be_fatal(self.benches.benchs[0].validate_parameters)
        self.should_be_fatal(self.benches.benchs[1].validate_parameters)
