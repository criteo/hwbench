#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import time

from .bench import benchmarks
from .config import config
from .environment import software as env_soft
from .environment import hardware as env_hw
from .utils import helpers as h
from .tuning import setup as tuning_setup
from .utils.hwlogging import init_logging


def main():
    if not is_root():
        h.fatal("hwbench is not running as effective uid 0.")

    out_dir, tuning_out_dir = create_output_directory()
    args = parse_options()

    # configure logging
    init_logging(tuning_out_dir / "hwbench-tuning.log")

    tuning_setup.Tuning(tuning_out_dir).apply()
    env = env_soft.Environment(out_dir)
    hw = env_hw.Hardware(out_dir)

    benches = benchmarks.Benchmarks(out_dir, config.Config(args.config), hw)
    benches.parse_config()
    results = benches.run()
    benches.dump()

    out = format_output(env.dump(), hw.dump(), results)

    write_output(out_dir, out)


def is_root():
    # euid != uid. please keep it this way (set-uid)
    return os.geteuid() == 0


def create_output_directory() -> tuple[pathlib.Path, pathlib.Path]:
    out_dir = pathlib.Path(f"hwbench-out-{time.strftime('%Y%m%d%H%M%S')}")
    out_dir.mkdir()
    tuning_out_dir = out_dir / "tuning"
    tuning_out_dir.mkdir()

    return out_dir, tuning_out_dir


def parse_options():
    parser = argparse.ArgumentParser(
        prog="hwbench",
        description="Criteo Hardware Benchmarking tool",
    )
    parser.add_argument(
        "-c", "--config", help="Specify the config file to load", required=True
    )
    return parser.parse_args()


def format_output(env, hw, results) -> dict[str, object]:
    return {
        "environment": env,
        "hardware": hw,
        "bench": results,
    }


def write_output(out_dir: pathlib.Path, out):
    out_file = out_dir / "results.json"
    print(f"Result file available at {str(out_file)}")
    out_file.write_text(json.dumps(out))


if __name__ == "__main__":
    # don't add anything here setup.py points at main()
    main()
