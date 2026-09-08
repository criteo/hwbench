from unittest.mock import patch

from hwbench.bench import test_benchmarks_common as tbc
from hwbench.environment.mock import MockHardware


class TestParseConfig(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hw = MockHardware()
        self.load_benches("./hwbench/config/pantheon.conf")

    def test_sections_name(self):
        """Check if sections names are properly detected."""
        sections = self.get_jobs_config().get_sections()
        assert sections == [
            "burn_all_gpus",
            "burn_two_gpus",
            "gpu_ladder",
            "whole_suite",
        ]

    def test_keywords(self):
        """Check if all keywords are valid."""
        try:
            with (
                patch("hwbench.utils.helpers.is_binary_available", return_value=True),
                patch("hwbench.environment.hardware.list_gpus", return_value=tbc.fake_gpus(4)),
            ):
                self.get_jobs_config().validate_sections()
        except Exception as exc:
            raise AssertionError(f"'validate_sections' detected a syntax error {exc}")

    def test_invalid_keywords(self):
        """Check if invalid custom parameters are detected."""
        self.load_benches("./hwbench/config/pantheon_weirds.conf")
        for section in [
            "bad_gpu_scaling",
            "bad_gpu_list",
            "unknown_gpu",
            "several_groups_at_once",
            "bad_memory_percent",
            "bad_boolean",
            "bad_platform",
            # A workload of another suite is not a parameter of this module.
            "wrong_suite",
            # A custom parameter must not stop the validation of the directives
            # declared after it.
            "custom_then_invalid_emp",
        ]:
            with (
                patch("hwbench.utils.helpers.is_binary_available", return_value=True),
                patch("hwbench.environment.hardware.list_gpus", return_value=tbc.fake_gpus(4)),
            ):
                self.should_be_fatal(self.get_jobs_config().validate_section, section)


class TestSelectedGpus(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hw = MockHardware()
        self.load_benches("./hwbench/config/pantheon.conf")

    def selected_gpus(self, value: str, gpus: int = 4):
        self.get_jobs_config().get_section("burn_all_gpus")["selected_gpus"] = value
        with patch("hwbench.environment.hardware.list_gpus", return_value=tbc.fake_gpus(gpus)):
            return self.get_jobs_config().get_selected_gpus("burn_all_gpus")

    def test_all(self):
        assert self.selected_gpus("all") == [0, 1, 2, 3]
        assert self.selected_gpus("all", gpus=0) == []

    def test_explicit(self):
        assert self.selected_gpus("0") == [0]
        assert self.selected_gpus("0,2") == [0, 2]
        assert self.selected_gpus("0-3") == [0, 1, 2, 3]
        assert self.selected_gpus("0 0,1 0-3") == [[0], [0, 1], [0, 1, 2, 3]]

    def test_unknown_gpu_is_fatal(self):
        self.should_be_fatal(self.selected_gpus, "0,7")

    def test_syntax(self):
        from hwbench.config.config_syntax import validate_selected_gpus

        for value in ["all", "0", "0,3", "0-7", "0 0,1 0-3"]:
            assert validate_selected_gpus(self.get_jobs_config(), "burn_all_gpus", value) == ""
        assert validate_selected_gpus(self.get_jobs_config(), "burn_all_gpus", "gpu0") == (
            "Unhandled string 'gpu0' in selected gpus"
        )
        assert validate_selected_gpus(self.get_jobs_config(), "burn_all_gpus", "0,,1") == (
            "Unhandled string '' in selected gpus"
        )


class TestSuites:
    def test_every_workload_belongs_to_a_module(self):
        """Every pantheon workload must be reachable from a job file."""
        from hwbench.engines.pantheon import SUITES, Engine

        engine = Engine()
        for suite, tests in SUITES.items():
            module = engine.get_module(suite)
            assert module
            assert module.get_module_parameters() == sorted(set(tests), key=tests.index)
