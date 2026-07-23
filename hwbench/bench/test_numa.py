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
        self.NUMA0_7 = list(range(0, self.hw.get_cpu().get_logical_cores_count()))
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
            self.should_be_fatal(self.get_jobs_config().get_selected_cpus, test_name)

    def test_numa_simple(self):
        """Check the numa-simple helper accumulates NUMA nodes one at a time."""
        cpu = self.hw.get_cpu()
        assert cpu.get_numa_domains_count() == 8
        # Cumulative groups: NUMA0, NUMA0-1, NUMA0-2, ... in domain order, cores sorted.
        cumulative_numa_nodes = []
        cores: list[int] = []
        for domain in range(cpu.get_numa_domains_count()):
            cores += cpu.get_logical_cores_in_numa_domain(domain)
            cumulative_numa_nodes.append(sorted(cores))

        # Sanity check against the known topology of this mocked AMD system
        assert cumulative_numa_nodes[0] == self.NUMA0
        assert cumulative_numa_nodes[1] == self.NUMA0_1
        assert cumulative_numa_nodes[7] == self.NUMA0_7

        assert self.get_jobs_config().get_selected_cpus("numa_simple") == cumulative_numa_nodes

        # numa_simple benchmarks are scheduled after numa_nodes (5) and quadrants (4)
        for index, numa_node in enumerate(cumulative_numa_nodes):
            assert self.get_bench_parameters(9 + index).get_pinned_cpu() == numa_node

    def test_numa_dump(self):
        """The CPU dump exposes the NUMA topology: node->cores and distance matrix."""
        dump = self.hw.get_cpu().dump()
        # NUMA node -> logical cores mapping
        assert dump["numa_domains"] == 8
        assert set(dump["numa_nodes"].keys()) == set(range(8))
        assert dump["numa_nodes"][0] == self.NUMA0
        assert dump["numa_nodes"][1] == self.NUMA1
        assert dump["numa_nodes"][7] == self.NUMA7
        # NUMA distance matrix: 8x8, local node is 10, node 0<->1 is 11, rest 12
        distances = dump["numa_distances"]
        assert len(distances) == 8
        assert distances[0] == [10, 11, 12, 12, 12, 12, 12, 12]
        for domain in range(8):
            assert len(distances[domain]) == 8
            assert distances[domain][domain] == 10

    def test_numa(self):
        """Check numa syntax"""
        assert self.hw.logical_core_count() == 128
        assert self.hw.get_cpu().get_vendor() == "AuthenticAMD"
        assert self.hw.get_cpu().get_numa_domains_count() == 8
        assert self.hw.get_cpu().get_quadrants_count() == 4
        assert self.get_jobs_config().get_selected_cpus("numa_nodes") == [
            self.NUMA0,
            self.NUMA1,
            self.NUMA7,
            self.NUMA0_7,
            self.NUMA0_1,
        ]

        assert self.get_bench_parameters(0).get_pinned_cpu() == self.NUMA0
        assert self.get_bench_parameters(1).get_pinned_cpu() == self.NUMA1
        assert self.get_bench_parameters(2).get_pinned_cpu() == self.NUMA7
        assert self.get_bench_parameters(3).get_pinned_cpu() == self.NUMA0_7
        assert self.get_bench_parameters(4).get_pinned_cpu() == self.NUMA0_1

        # Testing broken syntax that must fail
        # Testing quadrants
        self.load_benches("./hwbench/config/sample_weirds.conf")
        for test_name in [
            "invalid_numa_nodes",
            "alpha_numa_nodes",
        ]:
            self.should_be_fatal(self.get_jobs_config().get_selected_cpus, test_name)
