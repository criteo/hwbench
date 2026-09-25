from unittest.mock import patch

import pytest

from hwbench.bench import test_benchmarks_common as tbc


class TestParseConfig(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The validation of selected_cpus_scaling needs the cpu topology
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/fio.conf")

    def test_sections_name(self):
        """Check if sections names are properly detected."""
        sections = self.get_jobs_config().get_sections()
        assert sections == [
            "randread_cmdline",
        ]

    def test_keywords(self):
        """Check if all keywords are valid."""
        try:
            with (
                patch("hwbench.utils.helpers.is_binary_available", return_value=None),
                patch("hwbench.engines.fio.Engine.validate_disks", return_value=None),
            ):
                self.get_jobs_config().validate_sections()
        except Exception as exc:
            pytest.fail(f"'validate_sections' detected a syntax error {exc}")

    def test_keywords_after_disks(self):
        """The keywords following the engine specific ones are validated too."""
        self.load_benches("./hwbench/config/fio_fail.conf")
        with (
            patch("hwbench.utils.helpers.is_binary_available", return_value=None),
            patch("hwbench.engines.fio.Engine.validate_disks", return_value=None),
            pytest.raises(SystemExit),
        ):
            self.get_jobs_config().validate_sections()
