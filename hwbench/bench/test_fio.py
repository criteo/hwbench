from . import test_benchmarks_common as tbc


class TestFio(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./config/fio.conf")
        self.parse_jobs_config()
        self.QUADRANT0 = list(range(0, 16)) + list(range(64, 80))
        self.QUADRANT1 = list(range(16, 32)) + list(range(80, 96))
        self.ALL = list(range(0, 128))

    def test_fio(self):
        """Check fio syntax."""
        assert self.benches.count_benchmarks() == 1
        assert self.benches.count_jobs() == 1
        assert self.benches.runtime() == 15
        self.assertIsNone(self.benches.benchs[0].validate_parameters())
        bench = self.get_bench_parameters(0)
        assert bench.get_name() == "randread_cmdline"
