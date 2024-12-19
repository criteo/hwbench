#!/usr/bin/env python3

import argparse
import dataclasses
import json
import os
import pathlib
import platform
import time

from .bench import benchmarks
from .bench.monitoring_structs import MonitorMetric
from .config import config
from .environment import software as env_soft
from .environment import hardware as env_hw
from packaging.version import Version
from .utils import helpers as h
from .tuning import setup as tuning_setup
from .utils.hwlogging import init_logging


def main():
    # Let's ensure no one is running below the expected python release
    min_python_release = "3.9"
    if Version(platform.python_version()) < Version(min_python_release):
        h.fatal(
            f"Current python version {platform.python_version()} is below minimal supported release : {min_python_release}"
        )

    args = parse_options()
    if not is_root():
        h.fatal("hwbench is not running as effective uid 0.")

    out_dir, tuning_out_dir = create_output_directory(args.output_directory)

    # configure logging
    init_logging(tuning_out_dir / "hwbench-tuning.log")

    tuning_setup.Tuning(tuning_out_dir).apply(args.tuning)
    env = env_soft.Environment(out_dir)
    hw = env_hw.Hardware(out_dir, args.monitoring_config)

    benches = benchmarks.Benchmarks(out_dir, config.Config(args.jobs_config, hw), hw)
    benches.parse_jobs_config()

    results = benches.run()
    benches.dump()

    out = format_output(env.dump(), hw.dump(), results, benches.jobs_config)

    write_output(out_dir, out)


def is_root():
    # euid != uid. please keep it this way (set-uid)
    return os.geteuid() == 0


def create_output_directory(directory) -> tuple[pathlib.Path, pathlib.Path]:
    out_dir = pathlib.Path(directory or f"hwbench-out-{time.strftime('%Y%m%d%H%M%S')}")
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
        "--tuning",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable or disable tuning: this is useful when you want to test the system as-is.",
    )
    return parser.parse_args()


def format_output(env, hw, results, config) -> dict[str, object]:
    return {
        "environment": env,
        "hardware": hw,
        "bench": results,
        "config": config.to_dict(),
    }


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, MonitorMetric):
            dc = dataclasses.asdict(o)
            # In this project, MonitorMetric is the only dataclass object
            # value & values should not be exported as they are internal attributes
            # So let's delete them from the output, that would be confusing
            dc.pop("values")
            dc.pop("value")
            return dc
        return super().default(o)


def write_output(out_dir: pathlib.Path, out):
    out_file = out_dir / "results.json"
    print(f"Result file available at {str(out_file)}")
    out_file.write_text(json.dumps(out, cls=EnhancedJSONEncoder))


if __name__ == "__main__":
    # don't add anything here setup.py points at main()
    main()
