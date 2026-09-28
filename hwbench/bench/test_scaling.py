import pytest

from . import scaling
from . import test_benchmarks_common as tbc


def steps(keyword: str, value: str, items: list, cpu=None) -> list[int]:
    """Return how many items each step takes, the steps of plus_<x> and curve starting at the first item."""
    return [len(step) for step in scaling.scaling(keyword, value, items, cpu)]


def test_scaling():
    """The same function gives the steps of both scalings, as indexes of the items."""
    groups = [[cpu] for cpu in range(8)]
    assert scaling.scaling("selected_cpus_scaling", "iterate", groups) == [[index] for index in range(8)]
    assert scaling.scaling("selected_cpus_scaling", "none", list(range(8))) == [list(range(8))]
    for keyword, items in (("selected_cpus_scaling", groups), ("stressor_range_scaling", list(range(1, 9)))):
        assert steps(keyword, "plus_1", items) == [1, 2, 3, 4, 5, 6, 7, 8]
        assert steps(keyword, "plus_2", items) == [2, 4, 6, 8]
    counts = list(range(1, 65))
    assert steps("stressor_range_scaling", "curve", counts) == [1, 2, 3, 4, 8, 16, 32, 48, 64]
    # a single item is a single step, whatever the value
    assert scaling.scaling("stressor_range_scaling", "plus_2", [4]) == [[0]]


class FakeSockets:
    """A cpu of identical sockets, core n being logical cpu n."""

    def __init__(self, cores_per_socket: int):
        self.cores_per_socket = cores_per_socket

    def get_socket(self, logical_cpu: int) -> int:
        return logical_cpu // self.cores_per_socket


def test_curve():
    """The +16 steps go up to the last core, and the end of each socket is a step."""
    cores = [[core] for core in range(320)]
    assert steps("selected_cpus_scaling", "curve", cores, FakeSockets(160)) == [1, 2, 3, 4, 8, 16, *range(32, 321, 16)]
    cores = [[core] for core in range(100)]
    assert steps("selected_cpus_scaling", "curve", cores, FakeSockets(50)) == [
        1,
        2,
        3,
        4,
        8,
        16,
        32,
        48,
        50,
        64,
        80,
        96,
        100,
    ]


def test_impossible_scalings():
    """Unknown values and impossible steps are reported with the message to show."""
    groups = [[cpu] for cpu in range(8)]
    for keyword, items, value, message in [
        ("stressor_range_scaling", list(range(8)), "pow2", "unknown value pow2"),
        ("stressor_range_scaling", list(range(8)), "iterate", "unknown value iterate"),
        ("stressor_range_scaling", list(range(8)), "none", "unknown value none"),
        ("selected_cpus_scaling", groups, "plus_0", "unknown value plus_0"),
        ("selected_cpus_scaling", groups, "plus_x", "unknown value plus_x"),
        ("stressor_range_scaling", list(range(8)), "plus_3", "plus_3 needs a multiple of 3 items, got 8"),
        ("selected_cpus_scaling", groups, "plus_3", "plus_3 needs a multiple of 3 items, got 8"),
        (
            "selected_cpus_scaling",
            list(range(8)),
            "curve",
            "curve needs groups to accumulate, like selected_cpus=each-core",
        ),
        ("selected_cpus_scaling", groups, "none", "none needs a single group of cpus, got several"),
    ]:
        with pytest.raises(ValueError, match=message):
            scaling.scaling(keyword, value, items)


class TestStressorScaling(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/stressor_scaling.conf")
        self.parse_jobs_config()

    def runs(self, job: str) -> list:
        return [
            (len(bench.get_parameters().get_pinned_cpu() or []), bench.get_parameters().get_engine_instances_count())
            for bench in self.get_benches().get_benchmarks()
            if bench.get_parameters().get_name() == job
        ]

    def test_plus_1_keeps_the_written_order(self):
        assert [stressors for _, stressors in self.runs("plus_1")] == [8, 1, 4]

    def test_plus_2(self):
        assert [stressors for _, stressors in self.runs("plus_2")] == [2, 4, 6, 8]

    def test_curve(self):
        assert [stressors for _, stressors in self.runs("curve")] == [1, 2, 3, 4, 8, 16, 32, 48, 64]

    def test_cpus_and_stressors(self):
        """The same scaling on both keywords: 2 more NUMA domains, and every 2nd stressor count."""
        assert self.runs("cpus_and_stressors") == [
            (cpus, stressors) for cpus in (32, 64, 96, 128) for stressors in (2, 8)
        ]


class TestStressorScalingImpossible(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/stressor_scaling_fail.conf")

    def test_not_a_multiple(self):
        """8 stressor counts cannot be taken 3 by 3."""
        with pytest.raises(SystemExit):
            self.parse_jobs_config()
