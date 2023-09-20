from . import test_benchmarks_common as tbc


class TestHelpers(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./config/helpers.conf")
        self.parse_config()

    def test_helpers(self):
        """Testing helper functions."""

        # Simple
        ## On a simple test and for a 64 core cpu, we must have 8 jobs created
        ## Each of them must have the number of logical cores listed below
        logical_cores = [2, 4, 6, 8, 16, 32, 64, 96, 128]
        for job in range(0, 9):
            assert self.bench_name(job) == "simple"
            assert (
                len(self.get_bench_parameters(job).get_pinned_cpu())
                == logical_cores[job]
            )
