import pytest

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

    def test_socket(self):
        """Each logical cpu belongs to the socket of its physical core."""
        cpu = self.hw.get_cpu()
        assert cpu.get_socket(0) == 0
        assert cpu.get_socket(53) == 0
        assert cpu.get_socket(18) == 1
        assert cpu.get_socket(71) == 1
        assert cpu.get_socket(72) is None


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

        with pytest.raises(SystemExit):
            self.parse_jobs_config()


class TestHelpers_SingleNumaDomain(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The AMD EPYC 8534P set with a single NUMA domain (NPS1)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/1domain",
        )
        self.load_benches("./hwbench/config/numa_simple.conf")
        self.parse_jobs_config()

    def test_numa_simple_single_domain(self):
        """A helper giving a single group gives a single benchmark on it, not one per cpu."""
        assert self.get_benches().count_benchmarks() == 1
        assert self.get_bench_parameters(0).get_pinned_cpu() == list(range(0, 128))


class TestHelpers_Each(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/each.conf")
        self.parse_jobs_config()

    def pinnings(self, job: str) -> list:
        return [
            bench.get_parameters().get_pinned_cpu()
            for bench in self.get_benches().get_benchmarks()
            if bench.get_parameters().get_name() == job
        ]

    def test_each(self):
        """each-core, each-numa and each-quadrant give one group per item of the topology."""
        # 64 physical cores, core n owning logical cpus n and n+64
        assert self.pinnings("each_core") == [[core, core + 64] for core in range(64)]
        # 8 NUMA domains of 8 physical cores
        numa = [
            list(range(8 * domain, 8 * domain + 8)) + list(range(64 + 8 * domain, 72 + 8 * domain))
            for domain in range(8)
        ]
        assert self.pinnings("each_numa") == numa
        # 4 quadrants of 2 NUMA domains
        assert self.pinnings("each_quadrant") == [
            sorted(numa[2 * quadrant] + numa[2 * quadrant + 1]) for quadrant in range(4)
        ]

    def test_each_numa_plus_1(self):
        """each-numa with a plus_1 scaling adds one NUMA domain at each step, like numa-simple."""
        assert len(self.pinnings("each_numa_plus_1")) == 8
        assert self.pinnings("each_numa_plus_1") == self.pinnings("numa_simple")


class TestHelpers_EachSingleNumaDomain(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The AMD EPYC 8534P set with a single NUMA domain (NPS1)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/1domain",
        )
        self.load_benches("./hwbench/config/each.conf")
        self.parse_jobs_config()

    def test_each_numa_single_domain(self):
        """A single NUMA domain gives a single benchmark on it, not one per cpu."""
        pinnings = [
            bench.get_parameters().get_pinned_cpu()
            for bench in self.get_benches().get_benchmarks()
            if bench.get_parameters().get_name() == "each_numa"
        ]
        assert pinnings == [list(range(128))]
