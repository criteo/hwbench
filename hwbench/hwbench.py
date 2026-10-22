#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import platform
import shutil
import tempfile
import time

from packaging.version import Version

from .bench import benchmarks, cpumap
from .config import config
from .environment import hardware as env_hw
from .environment import software as env_soft
from .tuning import setup as tuning_setup
from .utils import helpers as h
from .utils.archive import RESULTS_FILE, create_output_archive
from .utils.hwlogging import init_logging


def main():
    # Let's ensure no one is running below the expected python release
    min_python_release = "3.9"
    if Version(platform.python_version()) < Version(min_python_release):
        h.fatal(
            f"Current python version {platform.python_version()} is below minimal supported release : {min_python_release}"
        )

    args = parse_options()
    if args.dry_run:
        return dry_run(args)

    if not is_root():
        h.fatal("hwbench is not running as effective uid 0.")

    timestamp = time.strftime("%Y%m%d%H%M%S")
    out_dir, tuning_out_dir = create_output_directory(args.output_directory, timestamp)

    # configure logging
    init_logging(tuning_out_dir / "hwbench-tuning.log")

    hwbench_config = config.Config(args.jobs_config)
    benches = benchmarks.Benchmarks(out_dir, hwbench_config, verbose=args.verbose)

    problems = env_hw.check_requirements() + benches.check_requirements()
    if report_problems(problems):
        return problems

    if args.context and args.context.strip():
        print(f"Startup: Context of the run: {args.context.strip()}")
    print("Startup: Tuning host")
    tuning_setup.Tuning(tuning_out_dir).apply(args.tuning)
    print("Startup: Dumping software environment")
    env = env_soft.Environment(out_dir)
    print("Startup: Dumping hardware environment")
    hw = env_hw.Hardware(out_dir, args.monitoring_config)

    hwbench_config.set_hardware(hw)
    benches.set_hardware(hw)
    benches.parse_jobs_config()

    results = benches.run()
    benches.dump()

    out = format_output(env.dump(), hw.dump(), results, benches.jobs_config, args.context)

    write_output(out_dir, out)

    if args.archive:
        archive = create_output_archive(out_dir, out["hardware"]["dmi"]["serial"], timestamp)
        print(f"Compressed output directory available at {archive!s}")


def report_problems(problems: list[Exception]) -> bool:
    """Log the requirements that are not met, and return if there is any."""
    for problem in problems:
        logging.critical("Requirements are not met: %s", problem)
    return len(problems) > 0


def dry_run(args):
    """Validate the job file and show where each benchmark would run, without running anything.

    Only the CPU topology is detected: no tuning, no environment dump, no BMC or PDU
    connection, so it is fast and does not need root.
    """
    with tempfile.TemporaryDirectory(prefix="hwbench-dry-run-") as tmp:
        tmp_dir = pathlib.Path(tmp)
        hwbench_config = config.Config(args.jobs_config)
        benches = benchmarks.Benchmarks(tmp_dir, hwbench_config, verbose=args.verbose, dry_run=True)

        problems = benches.check_requirements()
        if report_problems(problems):
            return problems

        hw = env_hw.CpuOnlyHardware(tmp_dir)
        hwbench_config.set_hardware(hw)
        benches.set_hardware(hw)
        benches.parse_jobs_config()

        print(cpumap.render(benches, width=shutil.get_terminal_size().columns))
    return None


def is_root():
    # euid != uid. please keep it this way (set-uid)
    return os.geteuid() == 0


def create_output_directory(directory, timestamp: str) -> tuple[pathlib.Path, pathlib.Path]:
    out_dir = pathlib.Path(directory or f"hwbench-out-{timestamp}")
    if out_dir.exists():
        h.fatal(f"Directory {out_dir} already exists, please give a non-existent directory.")
    out_dir.mkdir()
    tuning_out_dir = out_dir / "tuning"
    tuning_out_dir.mkdir()

    return out_dir.absolute(), tuning_out_dir.absolute()


def parse_options():
    parser = argparse.ArgumentParser(
        prog="hwbench",
        description="Criteo Hardware Benchmarking tool",
        epilog="Note that hwbench needs to run as root, for many reasons: system-wide tuning, local IPMI link to the BMC, x86 performance with turbostat, devices access with fio, etc.",
    )
    parser.add_argument(
        "-j",
        "--jobs-config",
        help="Specify the file containing jobs to runs",
        required=True,
    )
    parser.add_argument(
        "-m",
        "--monitoring-config",
        help="Specify the file containing the credentials to monitor the BMC",
    )
    parser.add_argument(
        "-o",
        "--output-directory",
        help="Specify the directory used to put all results and collected information",
    )
    parser.add_argument(
        "-c",
        "--context",
        help="A short text describing the context of the run, like 'bios-v2' or 'new thermal paste': kept in results.json, shown in the graphs of hwgraph, and used to find the runs with hwgraph graph --auto-traces.",
    )
    parser.add_argument(
        "--tuning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable tuning: this is useful when you want to test the system as-is.",
    )
    parser.add_argument(
        "--archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable the compressed copy of the output directory, hwbench-<serial>-<timestamp>.tar.xz, written next to it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate the jobs file and print the CPU map of every benchmark, without running anything. Does not need root.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    return parser.parse_args()


def format_output(env, hw, results, config, context: str | None = None) -> dict[str, object]:
    out = {
        "environment": env,
        "hardware": hw,
        "bench": results,
        "config": config.to_dict(),
    }
    # The context of the run is optional: only kept when given
    if context and context.strip():
        out["context"] = context.strip()
    return out


def write_output(out_dir: pathlib.Path, out):
    out_file = out_dir / RESULTS_FILE
    print(f"Result file available at {out_file!s}")
    out_file.write_text(json.dumps(out))


if __name__ == "__main__":
    # don't add anything here setup.py points at main()
    main()
