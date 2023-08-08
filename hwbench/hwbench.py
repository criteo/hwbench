#!/usr/bin/env python3

import argparse
import json
import logging
import os
import pathlib
import sys
import time

from .bench import stressng
from .environment import software as env_soft
from .environment import hardware as env_hw
from .tuning import setup as tuning_setup


def is_root():
    # euid != uid. please keep it this way (set-uid)
    return os.geteuid() == 0


def main():
    if not is_root():
        logging.error("hwbench is not running as effective uid 0.")
        sys.exit(1)

    out_dir = pathlib.Path(f"hwbench-out-{time.strftime('%Y%m%d%H%M%S')}")
    out_dir.mkdir()
    tuning_out_dir = out_dir / "tuning"
    tuning_out_dir.mkdir()
    benchmarks = {"qsort": stressng.StressNG(out_dir)}
    parser = argparse.ArgumentParser(
        prog="hwbench",
        description="Criteo Hardware Benchmarking tool",
    )
    parser.add_argument(
        "-b",
        "--bench",
        help="Specify which benchmark(s) to run",
        nargs="*",
        choices=list(benchmarks.keys()),
        default=list(benchmarks.keys())[0:1],
    )
    parser.add_argument("output", help="Name of output file", nargs="?", default=None)
    args = parser.parse_args()

    tuning_setup.Tuning(tuning_out_dir).apply()
    env = env_soft.Environment(out_dir).dump()
    hw = env_hw.Hardware(out_dir).dump()
    results = {}
    for b in args.bench:
        results[b] = benchmarks[b].run()

    output_file = args.output
    out = {
        "environment": env,
        "hardware": hw,
        "bench": results,
    }
    if not output_file:
        print(out)
    output_file = "hwbench-out-%s-%s.json" % (
        ",".join(args.bench),
        time.strftime("%Y%m%d%H%M%S"),
    )
    with open(output_file, "w") as f:
        f.write(json.dumps(out))


if __name__ == "__main__":
    # don't add anything here setup.py points at main()
    main()
