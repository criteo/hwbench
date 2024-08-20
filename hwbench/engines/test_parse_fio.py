import pathlib
import unittest
from unittest.mock import patch

from .fio import Engine as Fio


def mock_engine() -> Fio:
    with patch("hwbench.utils.helpers.is_binary_available") as iba:
        iba.return_value = True
        return Fio()


class TestParse(unittest.TestCase):
    def test_engine_parsing_version(self):
        test_dir = pathlib.Path("./hwbench/tests/parsing/fio")
        for d in test_dir.iterdir():
            test_target = mock_engine()
            if not d.is_dir():
                continue
            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()
            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_bytes().strip()
            assert test_target.version_major() == 3
            assert test_target.version_minor() == 19
