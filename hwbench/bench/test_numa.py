from . import test_benchmarks_common as tbc


class TestNuma(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        self.NUMA0 = [0, 1, 2, 3, 4, 5, 6, 7, 64, 65, 66, 67, 68, 69, 70, 71]
        self.NUMA1 = [8, 9, 10, 11, 12, 13, 14, 15, 72, 73, 74, 75, 76, 77, 78, 79]
        self.NUMA0_1 = sorted(self.NUMA0 + self.NUMA1)
        self.NUMA7 = [
            56,
            57,
            58,
            59,
            60,
            61,
            62,
            63,
            120,
            121,
            122,
            123,
            124,
            125,
            126,
            127,
        ]
        self.load_benches("./config/numa.conf")
        self.parse_config()

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
        self.load_benches("./config/sample_weirds.conf")
        with self.assertRaises(SystemExit):
            for test_name in [
                "invalid_numa_nodes",
                "alpha_numa_nodes",
                "invalid_quadrant",
                "alpha_quadrant",
            ]:
                self.get_config().get_hosting_cpu_cores(test_name)

    def test_numa(self):
        """Check numa syntax"""
        assert self.hw.logical_core_count() == 128
        assert self.hw.get_cpu().get_vendor() == "AuthenticAMD"
        assert self.hw.get_cpu().get_numa_domains_count() == 8
        assert self.hw.get_cpu().get_quadrants_count() == 4
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
        assert self.get_config().get_hosting_cpu_cores("numa_nodes") == [
            self.NUMA0,
            self.NUMA1,
            self.NUMA7,
            NUMA07,
            self.NUMA0_1,
        ]

        assert self.get_bench_parameters(0).get_pinned_cpu() == self.NUMA0
        assert self.get_bench_parameters(1).get_pinned_cpu() == self.NUMA1
        assert self.get_bench_parameters(2).get_pinned_cpu() == self.NUMA7
        assert self.get_bench_parameters(3).get_pinned_cpu() == NUMA07
        assert self.get_bench_parameters(4).get_pinned_cpu() == self.NUMA0_1
