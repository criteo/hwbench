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

        assert benches.count_benchmarks() == 195

        # Checking if each jobs as the right number of subjobs
        assert (
            benches.get_benchmarks()[0].get_parameters().get_name()
            == "check_1_core_int8_perf"
        )

        assert (
            benches.get_benchmarks()[1].get_parameters().get_name()
            == "check_1_core_qsort_perf"
        )

        # Checking if the first 64 jobs are check_all_cores_int8_perf
        for job in range(2, 65):
            assert (
                benches.get_benchmarks()[job].get_parameters().get_name()
                == "check_all_cores_int8_perf"
            )

        # Checking if remaining jobs are int8_8cores_16stressors
        for job in range(66, 194):
            assert (
                benches.get_benchmarks()[job].get_parameters().get_name()
                == "int8_8cores_16stressors"
            )

        # Checking if the last job is sleep
        assert benches.get_benchmarks()[-1].get_parameters().get_name() == "sleep"
