from __future__ import annotations

import pathlib
from unittest.mock import patch

from hwbench.environment import network


def test_dump_network(tmp_path):
    """The addresses are saved once, then the link of every interface, each in its own file."""
    with (
        patch("os.listdir", return_value=["eth1", "lo", "eth0"]) as listdir,
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = b"output"
        run.return_value.stderr = b""
        network.dump_network(tmp_path)
    listdir.assert_called_once_with(network.NET_CLASS)
    assert [call.args[0] for call in run.call_args_list] == [
        ["ip", "address"],
        ["ethtool", "eth0"],
        ["ethtool", "eth1"],
        ["ethtool", "lo"],
    ]
    assert sorted(path.name for path in pathlib.Path(tmp_path).iterdir()) == [
        "ethtool-eth0-stdout",
        "ethtool-eth1-stdout",
        "ethtool-lo-stdout",
        "ip-address-stdout",
    ]
