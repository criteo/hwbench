from __future__ import annotations

import logging
import pathlib
from unittest.mock import patch

from hwbench.environment.packages import DpkgList
from hwbench.environment.software import Environment


def list_packages(tmp_path: pathlib.Path, binaries: list[str]) -> list[str]:
    """Run package_lists() with only the given binaries installed, return the package lists made."""
    env = Environment.__new__(Environment)
    env.out_dir = tmp_path
    ran = []
    with (
        patch("shutil.which", side_effect=lambda binary: binary if binary in binaries else None),
        patch("hwbench.utils.external.External.run", lambda self: ran.append(self.name)),
    ):
        env.package_lists()
    return ran


def test_package_lists(tmp_path):
    """Every package manager present lists its packages."""
    assert list_packages(tmp_path, ["rpm"]) == ["rpm-list"]
    assert list_packages(tmp_path, ["dpkg-query"]) == ["dpkg-list"]
    assert list_packages(tmp_path, ["rpm", "dpkg-query"]) == ["rpm-list", "dpkg-list"]


def test_package_lists_missing(tmp_path, caplog):
    """Without any package manager, hwbench warns and goes on."""
    with caplog.at_level(logging.WARNING):
        assert list_packages(tmp_path, []) == []
    assert "Cannot find rpm or dpkg-query, the installed packages are not listed" in caplog.text


def test_dpkg_list(tmp_path):
    """The dpkg database is listed and its version parsed from the dpkg-query output."""
    dpkg = DpkgList(tmp_path)
    assert (
        dpkg.parse_version(b"Debian dpkg-query package management program version 1.22.6 (amd64).\n", b"") == "1.22.6"
    )
    assert dpkg.parse_cmd(b"zlib1g 1:1.3 amd64\nacl 2.3.2-2 amd64\n", b"") == [
        "acl 2.3.2-2 amd64",
        "zlib1g 1:1.3 amd64",
    ]
