from __future__ import annotations

import pathlib
import tarfile
from unittest.mock import patch

from hwbench.utils.archive import RESULTS_FILE, create_output_archive, extract_results_from_archive


def make_output_directory(tmp_path: pathlib.Path) -> pathlib.Path:
    out_dir = tmp_path / "hwbench-out-20261022100000"
    (out_dir / "tuning").mkdir(parents=True)
    (out_dir / RESULTS_FILE).write_text('{"bench": {}}')
    (out_dir / "tuning" / "hwbench-tuning.log").write_text("log")
    return out_dir


def test_archive_name_and_content(tmp_path):
    """The archive is named after the serial and the timestamp, and extracts as the output directory."""
    out_dir = make_output_directory(tmp_path)
    archive = create_output_archive(out_dir, "CZ2D2W09FR", "20261022100000")
    assert archive == tmp_path / "hwbench-CZ2D2W09FR-20261022100000.tar.xz"
    with tarfile.open(archive) as tarfd:
        assert sorted(tarfd.getnames()) == [
            "hwbench-out-20261022100000",
            "hwbench-out-20261022100000/results.json",
            "hwbench-out-20261022100000/tuning",
            "hwbench-out-20261022100000/tuning/hwbench-tuning.log",
        ]
    assert extract_results_from_archive(str(archive)) == b'{"bench": {}}'


def test_archive_sanitized_serial(tmp_path):
    """A serial the DMI does not give is replaced by the hostname, and one not usable in a filename is sanitized."""
    out_dir = make_output_directory(tmp_path)
    with patch("socket.gethostname", return_value="host01"):
        assert create_output_archive(out_dir, None, "1").name == "hwbench-host01-1.tar.xz"
        assert create_output_archive(out_dir, "  ", "3").name == "hwbench-host01-3.tar.xz"
    assert create_output_archive(out_dir, " To Be/Filled ", "2").name == "hwbench-To_Be_Filled-2.tar.xz"


def test_archive_without_results(tmp_path):
    """Only the results.json at the top of the output directory is the trace."""
    out_dir = make_output_directory(tmp_path)
    (out_dir / RESULTS_FILE).rename(out_dir / "tuning" / RESULTS_FILE)
    archive = create_output_archive(out_dir, "serial", "1")
    assert extract_results_from_archive(str(archive)) is None
