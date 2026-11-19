from __future__ import annotations

import os
import pathlib

from hwbench.utils.external import External_Simple

NET_CLASS = "/sys/class/net"


def dump_network(out_dir: pathlib.Path):
    """Save the network configuration: the addresses of the interfaces, then the link of each of them."""
    External_Simple(out_dir, ["ip", "address"], "ip-address")
    for interface in sorted(os.listdir(NET_CLASS)):
        External_Simple(out_dir, ["ethtool", interface], f"ethtool-{interface}")
