import pathlib
from unittest.mock import patch
from . import benchmarks
from ..config import config


class TestParse(object):
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
            benches = benchmarks.Benchmarks(".", config.Config("config/sample.ini"))
            benches.parse_config()

        def bench_name(index) -> str:
            """Return the benchmark name"""
            return benches.get_benchmarks()[index].get_parameters().get_name()

        def bench_em(index) -> str:
            """Return the benchmark engine module name"""
            return benches.get_benchmarks()[index].get_enginemodule().get_name()

        def bench_emp(index) -> str:
            """Return the benchmark engine module parameter"""
            return (
                benches.get_benchmarks()[index]
                .get_parameters()
                .get_engine_module_parameter()
            )

        def assert_job(index, name, engine_module, engine_module_parameter=None):
            """Assert if a benchmark does not match the config file description."""
            # If not engine_module_parameter set, let's consider the engine_module
            if not engine_module_parameter:
                engine_module_parameter = engine_module
            assert bench_name(index) == name
            assert bench_em(index) == engine_module
            assert bench_emp(index) == engine_module_parameter

        assert benches.count_benchmarks() == 197

        # Checking if each jobs as the right number of subjobs
        assert_job(0, "check_1_core_int8_perf", "cpu", "int8")
        assert_job(1, "check_1_core_int8_float_perf", "cpu", "int8")
        assert_job(2, "check_1_core_int8_float_perf", "cpu", "float")
        assert_job(3, "check_1_core_qsort_perf", "qsort")

        # Checking if the first 64 jobs are check_all_cores_int8_perf
        for job in range(4, 67):
            assert_job(job, "check_all_cores_int8_perf", "cpu", "int8")

        # Checking if remaining jobs are int8_8cores_16stressors
        for job in range(68, 196):
            assert_job(job, "int8_8cores_16stressors", "cpu", "int8")

        # Checking if the last job is sleep
        assert_job(-1, "sleep", "sleep")
