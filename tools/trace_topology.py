#!/usr/bin/env python3

"""Locate the traces of hwbench again with a topology file, as hwbench would have with -t.

The location of each trace, found by the serial of its server, is written again from the
topology: its places, and its label and ASHRAE classes since the version 2 of the format. The
topology replaces the copy the trace keeps. A topology of the version 2 gives the label and the
classes to traces run with a topology of the version 1, or without any; one of the version 1 removes
them. A trace whose server is not in the topology is left unchanged.
The traces are processed by --jobs workers, an archive in xz being compressed by the xz command on
the cores the workers leave, as compressing takes almost all the time.
See documentation/topology.md.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import io
import json
import lzma
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

from graph.common import DEFAULT_JOBS, progress
from hwbench.environment import ashrae, cooling
from hwbench.environment.environment_file import Location
from hwbench.environment.topology import TOPOLOGY_FILE, find_server, location_output, read_topology
from hwbench.utils.archive import RESULTS_FILE, archive_output_directory

# The xz command, multithreaded, used instead of the lzma module (a single thread) when installed
XZ = shutil.which("xz")

# The compression of an archive, from its suffix, kept when it is written again
COMPRESSIONS: dict[str, Callable[..., Any]] = {
    ".xz": lzma.open,
    ".gz": gzip.open,
    ".tgz": gzip.open,
    ".bz2": bz2.open,
}


def parse_options(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trace_topology.py",
        description="Locate the traces of hwbench again with a topology file, as hwbench would have with -t.",
    )
    parser.add_argument("topology", help="The topology file, like topology.json")
    parser.add_argument(
        "traces",
        nargs="+",
        help="The traces: an archive of hwbench, a results.json, or a directory searched for both",
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="Print what would change, without writing")
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"The traces processed at once (default: {DEFAULT_JOBS}); "
        "each archive in xz is compressed on the cores the others leave",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def trace_files(paths: list[str]) -> list[pathlib.Path]:
    """The archives and the results.json of the paths, a directory being searched for both: the
    results.json of an output directory also archived next to it is the same run, only the archive is kept."""
    found = []
    for path in map(pathlib.Path, paths):
        if not path.is_dir():
            found.append(path)
            continue
        archived = set()
        for archive in sorted(path.rglob("*.tar*")):
            try:
                output_directory = archive_output_directory(str(archive))
            except (OSError, tarfile.TarError, EOFError):
                continue
            if output_directory:
                found.append(archive)
                archived.add(archive.parent.resolve() / output_directory)
        found += [results for results in sorted(path.rglob(RESULTS_FILE)) if results.parent.resolve() not in archived]
    return found


class TraceFiles:
    """The results.json of a trace and the copy of its topology, in an archive or in a directory."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.archive = path.name != RESULTS_FILE
        if self.archive:
            output_directory = archive_output_directory(str(path))
            if not output_directory:
                raise ValueError(f"no {RESULTS_FILE} in the archive")
            with tarfile.open(path) as source:
                self.members = [(m, source.extractfile(m).read() if m.isfile() else None) for m in source]  # type: ignore[union-attr]
            self.names = {
                file: next(
                    (
                        member.name
                        for member, _ in self.members
                        if pathlib.PurePosixPath(member.name).parts == (output_directory, file)
                    ),
                    f"{output_directory}/{file}",
                )
                for file in (RESULTS_FILE, TOPOLOGY_FILE)
            }

    def read(self, file: str) -> bytes | None:
        if not self.archive:
            target = self.path.with_name(file)
            return target.read_bytes() if target.exists() else None
        return next((data for member, data in self.members if member.name == self.names[file]), None)

    def write(self, files: dict[str, bytes], xz_threads: int = 1) -> None:
        """Write these files of the trace, an archive being written again whole, with its compression:
        an archive in xz by the xz command on <xz_threads> threads when it is installed."""
        if not self.archive:
            for file, data in files.items():
                self.path.with_name(file).write_bytes(data)
            return
        new = {self.names[file]: data for file, data in files.items()}
        written = self.path.with_name(f".{self.path.name}.new")
        if self.path.suffix == ".xz" and XZ:
            with written.open("wb") as output:
                # The preset of the lzma module, and its check
                xz = subprocess.Popen([XZ, f"-T{xz_threads}", "-6", "-c"], stdin=subprocess.PIPE, stdout=output)
                assert xz.stdin is not None
                with xz.stdin, tarfile.open(fileobj=xz.stdin, mode="w|") as target:
                    self.write_members(target, new)
                if xz.wait():
                    written.unlink()
                    raise OSError(f"xz failed with the code {xz.returncode}")
        else:
            compress = COMPRESSIONS.get(self.path.suffix, open)
            with compress(written, "wb") as output, tarfile.open(fileobj=output, mode="w") as target:
                self.write_members(target, new)
        written.replace(self.path)

    def write_members(self, target: tarfile.TarFile, new: dict[str, bytes]) -> None:
        """The members of the archive into <target>, those of <new> replaced or added."""
        for member, content in self.members:
            content = new.pop(member.name, content)
            if content is None:
                target.addfile(member)
            else:
                member.size = len(content)
                target.addfile(member, io.BytesIO(content))
        # A trace run without topology gets its copy
        for name, data in new.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))


# What a trace became: located or not, and the line saying it, for the standard output or the error one
Outcome = tuple[bool, str, str]


def relocate(
    path: pathlib.Path, topology: dict, topology_content: bytes, dry_run: bool, xz_threads: int = 1
) -> Outcome:
    """Locate a trace again with the topology; not located when its server is not in it. The line is
    returned, not printed, as the workers would mix theirs with the progress bar."""
    try:
        files = TraceFiles(path)
        results = json.loads(files.read(RESULTS_FILE) or b"null")
        if not isinstance(results, dict) or "hardware" not in results:
            raise ValueError("not a trace of hwbench")
        serial = (results["hardware"].get("dmi", {}).get("serial") or "").strip()
        server = find_server(topology, serial) if serial else None
        if server is None:
            return False, "", f"{path}: the serial {serial!r} of its server is not in the topology, unchanged"

        location = location_output(server.location, server)
        previous = results.get("location")
        if previous == location and files.read(TOPOLOGY_FILE) == topology_content:
            return True, f"{path}: {serial}: unchanged", ""
        changes = [server.location.line()]
        if isinstance(previous, dict) and previous.get("path") != server.location.path:
            changes.append(f"moved from {Location.from_dict(previous).line()}")
        changes.append(f"label {server.label}" if server.label else "no label")
        changes.append(f"ASHRAE {ashrae.line(server.ashrae)}" if server.ashrae else "no ASHRAE classes")
        changes.append(f"cooling {cooling.line(server.cooling)}" if server.cooling else "no cooling")
        if not dry_run:
            results["location"] = location
            # As hwbench writes it
            files.write({RESULTS_FILE: json.dumps(results).encode(), TOPOLOGY_FILE: topology_content}, xz_threads)
        return True, f"{path}: {serial}: {', '.join(changes)}", ""
    except (ValueError, KeyError, OSError, tarfile.TarError, EOFError) as e:
        return False, "", f"{path}: {e}, unchanged"


def relocate_all(
    paths: list[pathlib.Path], topology: dict, topology_content: bytes, dry_run: bool, jobs: int
) -> Iterator[Outcome]:
    """What each trace became, in their order, <jobs> at once, each archive in xz compressed by the xz
    command on the cores the workers leave."""
    jobs = min(jobs, len(paths)) or 1
    xz_threads = max(1, (os.cpu_count() or 1) // jobs)
    if jobs == 1:
        yield from (relocate(path, topology, topology_content, dry_run, xz_threads) for path in paths)
        return
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        n = len(paths)
        yield from pool.map(relocate, paths, [topology] * n, [topology_content] * n, [dry_run] * n, [xz_threads] * n)


def main(argv: list[str] | None = None) -> int:
    args = parse_options(argv)
    topology, problems = read_topology(args.topology)
    if problems:
        print(f"{args.topology}: invalid topology, check it with tools/topology_check.py:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    topology_content = pathlib.Path(args.topology).read_bytes()

    paths = trace_files(args.traces)
    failed = 0
    for done, (located, line, problem) in enumerate(
        relocate_all(paths, topology, topology_content, args.dry_run, args.jobs), 1
    ):
        if line:
            print(line)
        if problem:
            print(problem, file=sys.stderr)
        failed += not located
        # On a terminal only: in a file, the line of each trace already says how far it is
        if sys.stdout.isatty():
            progress("trace_topology", done, len(paths), "traces")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
