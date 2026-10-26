#!/usr/bin/env python3

"""Check a topology file, the JSON description of where the servers are, before giving it to hwbench.

The file is valid when it follows the JSON schema of its version, printed with --schema, when
its serials are at the depth of its levels, under a known place, and each at a single place.
See documentation/topology.md.
"""

from __future__ import annotations

import argparse
import sys

from hwbench.environment.topology import (
    TOPOLOGY_VERSION,
    find_location,
    read_topology,
    schema_path,
    separator_warnings,
    servers,
)


def parse_options(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="topology_check.py",
        description="Check a topology file, the JSON description of where the servers are, before giving it to hwbench.",
    )
    parser.add_argument("topology", nargs="?", help="The topology file to check, like topology.json")
    parser.add_argument("-s", "--serial", help="Also print the location of the server of this serial")
    parser.add_argument(
        "--schema",
        action="store_true",
        help=f"Print the path of the JSON schema of the topology format, version {TOPOLOGY_VERSION}, and exit",
    )
    args = parser.parse_args(argv)
    if not args.schema and not args.topology:
        parser.error("the topology file is required")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_options(argv)
    if args.schema:
        print(schema_path())
        return 0

    topology, problems = read_topology(args.topology)
    if problems:
        print(f"{args.topology}: invalid topology:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    located = [location for _, location in servers(topology)]
    levels = topology.get("levels")
    hierarchy = f"the levels {' / '.join(levels)}" if levels else "no levels"
    print(f"{args.topology}: valid topology, version {topology['version']}, {hierarchy}: {len(located)} servers")
    for warning in separator_warnings(topology):
        print(f"{args.topology}: warning: {warning}", file=sys.stderr)
    if args.serial:
        location = find_location(topology, args.serial)
        if location is None:
            print(f"{args.serial}: not in the topology", file=sys.stderr)
            return 1
        print(f"{args.serial}: {location.line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
