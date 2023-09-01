import unittest
import pathlib
from unittest.mock import patch

from . import config


class TestParseConfig(unittest.TestCase):
    config_file = config.Config("./config/sample.ini")

    def test_sections_name(self):
        """Check if sections names are properly detected."""
        sections = self.config_file.get_sections()
        assert sections == [
            "check_1_core_int8_perf",
            "check_1_core_int8_float_perf",
            "check_1_core_qsort_perf",
            "check_all_cores_int8_perf",
            "int8_8cores_16stressors",
            "check_physical_core_int8_perf",
            "sleep",
        ]

    def test_keywords(self):
        """Check if all keywords are valid."""
        try:
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
                self.config_file.validate_sections()
        except Exception as exc:
            assert False, f"'validate_sections' detected a syntax error {exc}"

    def test_defaults(self):
        """Check if default values are properly set."""
        config_file = config.Config("./config/sample_weirds.conf")
        assert config_file.get_config().getint("noglobalruntime", "runtime") == 60

        # Now let's check an invalid syntax stop the tool
        with self.assertRaises(SystemExit) as cm:
            config_file.validate_section("engine_error")
            config_file.validate_section("runtime_error")
            config_file.validate_section("unknown_engine")
            config_file.validate_section("unknown_engine_module")
            config_file.validate_section("unknown_engine_module_parameter")
            config_file.validate_section("unknown_monitoring")
        # We must have triggered a SystemExit !
        self.assertEqual(cm.exception.code, 1)

    def test_range_list_input(self):
        """Check if parsing the range syntax is valid."""
        assert self.config_file.parse_range("1") == [1]
        assert self.config_file.parse_range("1,3,5") == [1, 3, 5]
        assert self.config_file.parse_range("1-5") == [1, 2, 3, 4, 5]
        assert self.config_file.parse_range("1-2,5-6") == [1, 2, 5, 6]
        assert self.config_file.parse_range("int8,float") == ["int8", "float"]
        assert self.config_file.parse_range("1-3 4-5") == [[1, 2, 3], [4, 5]]
        assert self.config_file.parse_range("1,32 2,33") == [[1, 32], [2, 33]]
