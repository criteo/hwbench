import pathlib
from unittest.mock import patch
from ..environment.mock import MockHardware
from ..bench import test_benchmarks_common as tbc


class TestParseConfig(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            p.return_value = (
                pathlib.Path("./hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
            )
            self.hw = MockHardware()
            self.load_benches("./hwbench/config/sample.ini")

    def test_sections_name(self):
        """Check if sections names are properly detected."""
        sections = self.get_jobs_config().get_sections()
        assert sections == [
            "check_1_core_int8_perf",
            "check_1_core_int8_float_perf",
            "check_1_core_qsort_perf",
            "check_all_cores_int8_perf",
            "int8_8cores_16stressors",
            "check_physical_core_int8_perf",
            "check_physical_core_scale_plus_1_int8_perf",
            "run_all_stressng_cpu",
            "sleep_all",
            "sleep",
        ]

    def test_keywords(self):
        """Check if all keywords are valid."""
        try:
            # We need to patch list_module_parameters() function
            # to avoid considering the local stress-ng binary
            with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
                p.return_value = (
                    pathlib.Path("./hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
                )
                with patch("hwbench.utils.helpers.is_binary_available") as iba:
                    iba.return_value = True
                    self.get_jobs_config().validate_sections()
        except Exception as exc:
            assert False, f"'validate_sections' detected a syntax error {exc}"

    def test_defaults(self):
        """Check if default values are properly set."""
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            p.return_value = (
                pathlib.Path("./hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
            )
            self.load_benches("./hwbench/config/sample_weirds.conf")
            assert self.get_jobs_config().get_config().getint("noglobalruntime", "runtime") == 60

            # Now let's check an invalid syntax stop the tool
            for section in [
                "engine_error",
                "runtime_error",
                "unknown_engine",
                "unknown_engine_module",
                "unknown_engine_module_parameter",
                "unknown_monitoring",
            ]:
                self.should_be_fatal(self.get_jobs_config().validate_section, section)

    def test_range_list_input(self):
        """Check if parsing the range syntax is valid."""
        assert self.get_jobs_config().parse_range("1") == [1]
        assert self.get_jobs_config().parse_range("1,3,5") == [1, 3, 5]
        assert self.get_jobs_config().parse_range("1-5") == [1, 2, 3, 4, 5]
        assert self.get_jobs_config().parse_range("1-2,5-6") == [1, 2, 5, 6]
        assert self.get_jobs_config().parse_range("int8,float") == ["int8", "float"]
        assert self.get_jobs_config().parse_range("1-3 4-5") == [[1, 2, 3], [4, 5]]
        assert self.get_jobs_config().parse_range("1,32 2,33") == [[1, 32], [2, 33]]
        with self.assertRaises(SystemExit):
            self.get_jobs_config().parse_range("bad,range,bad-range")
