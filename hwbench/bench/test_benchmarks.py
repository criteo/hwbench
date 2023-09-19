import pathlib
import unittest
from unittest.mock import patch
from . import benchmarks
from ..config import config
from ..environment.cpu import MockCPU
from ..environment.cpu_info import CPU_INFO
from ..environment.cpu_cores import CPU_CORES
from ..environment.numa import NUMA
from ..environment.mock import MockHardware


class TestParse(unittest.TestCase):
    def test_parsing(self):
        # We need to patch list_module_parameters() function
        # to avoid considering the local stress-ng binary
        with patch(
            "hwbench.engines.stressng.EngineModuleCpu.list_module_parameters"
        ) as p:
            p.return_value = (
                pathlib.Path("./tests/parsing/stressngmethods/v16/stdout")
                .read_bytes()
                .split(b":", 1)
            )
            hw = MockHardware(cores=64)
            benches = benchmarks.Benchmarks(
                ".", config.Config("config/sample.ini", hw), hw
            )
            benches.parse_config()

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        def bench_name(index) -> str:
            """Return the benchmark name"""
            return get_bench_parameters(index).get_name()

        def bench_em(index) -> str:
            """Return the benchmark engine module name"""
            return benches.get_benchmarks()[index].get_enginemodule().get_name()

        def bench_emp(index) -> str:
            """Return the benchmark engine module parameter"""
            return get_bench_parameters(index).get_engine_module_parameter()

        def assert_job(index, name, engine_module, engine_module_parameter=None):
            """Assert if a benchmark does not match the config file description."""
            # If not engine_module_parameter set, let's consider the engine_module
            if not engine_module_parameter:
                engine_module_parameter = engine_module
            assert bench_name(index) == name
            assert bench_em(index) == engine_module
            assert bench_emp(index) == engine_module_parameter

        assert benches.count_benchmarks() == 286
        assert benches.count_jobs() == 9
        assert benches.runtime() == 295

        # Checking if each jobs as the right number of subjobs
        assert_job(0, "check_1_core_int8_perf", "cpu", "int8")
        assert_job(1, "check_1_core_int8_float_perf", "cpu", "int8")
        assert_job(2, "check_1_core_int8_float_perf", "cpu", "float")
        assert_job(3, "check_1_core_qsort_perf", "qsort")

        # Checking if the first 64 jobs are check_all_cores_int8_perf
        for job in range(4, 68):
            assert_job(job, "check_all_cores_int8_perf", "cpu", "int8")

        # Checking if remaining jobs are int8_8cores_16stressors
        for job in range(68, 196):
            assert_job(job, "int8_8cores_16stressors", "cpu", "int8")

        for job in range(196, 199):
            assert_job(job, "check_physical_core_int8_perf", "cpu", "int8")
            # Ensure the auto syntax updated the number of engine instances
            if job == 198:
                instances = 4
            else:
                instances = 2
            assert get_bench_parameters(job).get_engine_instances_count() == instances

        group_count = 0
        for job in range(199, 203):
            group_count += 2
            assert_job(job, "check_physical_core_scale_plus_1_int8_perf", "cpu", "int8")
            assert get_bench_parameters(job).get_engine_instances_count() == group_count
            assert len(get_bench_parameters(job).get_pinned_cpu()) == group_count

        emp_all = (
            benches.get_benchmarks()[203].get_enginemodule().get_module_parameters()
        )
        emp_all.reverse()
        for job in range(203, 285):
            assert_job(job, "run_all_stressng_cpu", "cpu", emp_all.pop())
        # Checking if the last job is sleep
        assert_job(-1, "sleep", "sleep")

    def test_stream_short(self):
        with patch(
            "hwbench.engines.stressng.EngineModuleCpu.list_module_parameters"
        ) as p:
            p.return_value = (
                pathlib.Path("./tests/parsing/stressngmethods/v16/stdout")
                .read_bytes()
                .split(b":", 1)
            )
            config_file = config.Config("./config/stream.ini", MockHardware())
            assert config_file.get_config().getint("global", "runtime") == 5
            config_file.get_config().set("global", "runtime", "2")
            benches = benchmarks.Benchmarks(".", config_file, MockHardware())
            with self.assertRaises(SystemExit):
                benches.parse_config()

    def load_mocked_hardware(
        self,
        cpuinfo=None,
        cpucores=None,
        numa=None,
    ):
        def load(target, path):
            instance = target(path)
            stdout = (path / "stdout").read_bytes()
            stderr = (path / "stderr").read_bytes()
            instance.parse_cmd(stdout, stderr)
            return instance

        fake_numa = None
        if numa:
            fake_numa = load(NUMA, pathlib.Path(numa))

        fake_cpuinfo = None
        if cpuinfo:
            fake_cpuinfo = load(CPU_INFO, pathlib.Path(cpuinfo))

        fake_cpucores = None
        if cpucores:
            fake_cpucores = load(CPU_CORES, pathlib.Path(cpucores))

        cpu = MockCPU(".", fake_cpuinfo, fake_cpucores, fake_numa)
        return MockHardware(cpu=cpu)

    def test_cores(self):
        """Check cores syntax."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        hw = self.load_mocked_hardware(cpucores="./tests/parsing/cpu_cores/v2321")

        cfg = config.Config("./config/cores.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        benches.parse_config()
        CPU0 = [0, 64]
        CPU1 = [1, 65]
        CPU0_1 = sorted(CPU0 + CPU1)
        CPU0_7 = [0, 1, 2, 3, 4, 5, 6, 7, 64, 65, 66, 67, 68, 69, 70, 71]
        assert cfg.get_hosting_cpu_cores("cores") == [CPU0, CPU1, CPU0_7, CPU0_1]
        assert get_bench_parameters(0).get_pinned_cpu() == CPU0
        assert get_bench_parameters(1).get_pinned_cpu() == CPU1
        assert get_bench_parameters(2).get_pinned_cpu() == CPU0_7
        assert get_bench_parameters(3).get_pinned_cpu() == CPU0_1

        # Testing broken syntax that must fail
        cfg = config.Config("./config/sample_weirds.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        with self.assertRaises(SystemExit):
            cfg.get_hosting_cpu_cores("invalid_cpu_core")
            cfg.get_hosting_cpu_cores("alpha_cpu_core")

    def test_helpers(self):
        """Testing helper functions."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        def bench_name(index) -> str:
            """Return the benchmark name"""
            return get_bench_parameters(index).get_name()

        hw = self.load_mocked_hardware(
            cpucores="./tests/parsing/cpu_cores/v2321",
            cpuinfo="./tests/parsing/cpu_info/v2321",
            numa="./tests/parsing/numa/8domainsllc",
        )
        cfg = config.Config("./config/helpers.conf", hw)
        benches = benchmarks.Benchmarks(".", cfg, hw)
        benches.parse_config()

        # Simple
        ## On a simple test and for a 64 core cpu, we must have 8 jobs created
        ## Each of them must have the number of logical cores listed below
        logical_cores = [2, 4, 6, 8, 16, 32, 64, 96, 128]
        for job in range(0, 9):
            assert bench_name(job) == "simple"
            assert len(get_bench_parameters(job).get_pinned_cpu()) == logical_cores[job]

    def test_numa(self):
        """Check numa."""

        def get_bench_parameters(index):
            """Return the benchmark parameters."""
            return benches.get_benchmarks()[index].get_parameters()

        hw = self.load_mocked_hardware(
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
