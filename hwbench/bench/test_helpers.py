from . import test_benchmarks_common as tbc


class TestHelpers(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/helpers.conf")
        self.parse_jobs_config()

    def test_helpers(self):
        """Testing helper functions."""

        # Simple
        ## On a simple test and for a 64 core cpu, we must have 9 jobs created
        ## Each of them must have the number of logical cores listed below
        logical_cores = [2, 4, 6, 8, 16, 32, 64, 96, 128]
        assert self.get_benches().count_benchmarks() == 9
        for job in range(0, 9):
            assert self.bench_name(job) == "simple"
            assert len(self.get_bench_parameters(job).get_pinned_cpu()) == logical_cores[job]


class TestHelpers_CPUSTORAGE(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/cpustorage",
            cpuinfo="./hwbench/tests/parsing/cpu_info/cpustorage",
            numa="./hwbench/tests/parsing/numa/2domains",
        )
        self.load_benches("./hwbench/config/helpers.conf")
        self.parse_jobs_config()

    def test_helpers(self):
        """Testing helper functions."""

        # Simple
        ## On a simple test and for a dual socket 18 cores cpu, we must have 9 jobs created
        ## Each of them must have the number of logical cores listed below
        logical_cores = [2, 4, 6, 8, 16, 32, 36, 64, 72]
        assert self.get_benches().count_benchmarks() == 9
        for job in range(0, 8):
            assert self.bench_name(job) == "simple"
            assert len(self.get_bench_parameters(job).get_pinned_cpu()) == logical_cores[job]


class TestHelpersImpossible(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/helpers_fail.conf")

    def test_helpers_impossible(self):
        """Testing impossible helper usecase."""

        with self.assertRaises(SystemExit):
            self.parse_jobs_config()
