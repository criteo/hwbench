from unittest.mock import patch
from ..environment.mock import MockHardware
from ..bench import test_benchmarks_common as tbc


class TestParseConfig(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hw = MockHardware()
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
            with patch("hwbench.utils.helpers.is_binary_available") as iba:
                iba.return_value = True
                self.get_jobs_config().validate_sections()
        except Exception as exc:
            assert False, f"'validate_sections' detected a syntax error {exc}"
