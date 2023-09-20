import unittest
from . import benchmarks
from . import test_benchmarks_common as tbc
from ..config import config


class TestNuma(unittest.TestCase):
    def test_numa(self):
        """Check numa."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        hw = tbc.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        assert hw.logical_core_count() == 128
        assert hw.get_cpu().get_vendor() == "AuthenticAMD"
        assert hw.get_cpu().get_numa_domains_count() == 8
        assert hw.get_cpu().get_quadrants_count() == 4

        cfg = config.Config("./config/numa.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        benches.parse_config()
        NUMA0 = [0, 1, 2, 3, 4, 5, 6, 7, 64, 65, 66, 67, 68, 69, 70, 71]
        NUMA1 = [8, 9, 10, 11, 12, 13, 14, 15, 72, 73, 74, 75, 76, 77, 78, 79]
        NUMA0_1 = sorted(NUMA0 + NUMA1)
        NUMA7 = [56, 57, 58, 59, 60, 61, 62, 63, 120, 121, 122, 123, 124, 125, 126, 127]
        NUMA07 = [
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
            45,
            46,
            47,
            48,
            49,
            50,
            51,
            52,
            53,
            54,
            55,
            56,
            57,
            58,
            59,
            60,
            61,
            62,
            63,
            64,
            65,
            66,
            67,
            68,
            69,
            70,
            71,
            72,
            73,
            74,
            75,
            76,
            77,
            78,
            79,
            80,
            81,
            82,
            83,
            84,
            85,
            86,
            87,
            88,
            89,
            90,
            91,
            92,
            93,
            94,
            95,
            96,
            97,
            98,
            99,
            100,
            101,
            102,
            103,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            111,
            112,
            113,
            114,
            115,
            116,
            117,
            118,
            119,
            120,
            121,
            122,
            123,
            124,
            125,
            126,
            127,
        ]
        assert cfg.get_hosting_cpu_cores("numa_nodes") == [
            NUMA0,
            NUMA1,
            NUMA7,
            NUMA07,
            NUMA0_1,
        ]
        # Each quadrant is made of two numa nodes on this AMD system
        assert hw.get_cpu().get_cores_in_quadrant(0) == NUMA0_1

        assert get_bench_parameters(0).get_pinned_cpu() == NUMA0
        assert get_bench_parameters(1).get_pinned_cpu() == NUMA1
        assert get_bench_parameters(2).get_pinned_cpu() == NUMA7
        assert get_bench_parameters(3).get_pinned_cpu() == NUMA07
        assert get_bench_parameters(4).get_pinned_cpu() == NUMA0_1
        # Testing quadrants
        assert get_bench_parameters(5).get_pinned_cpu() == NUMA0_1
        assert len(get_bench_parameters(6).get_pinned_cpu()) == 32
        assert len(get_bench_parameters(7).get_pinned_cpu()) == 128
        assert len(get_bench_parameters(8).get_pinned_cpu()) == 64

        # Testing broken syntax that must fail
        cfg = config.Config("./config/sample_weirds.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        with self.assertRaises(SystemExit):
            for test_name in [
                "invalid_numa_nodes",
                "alpha_numa_nodes",
                "invalid_quadrant",
                "alpha_quadrant",
            ]:
                cfg.get_hosting_cpu_cores(test_name)
