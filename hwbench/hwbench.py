#!/usr/bin/env python3

import argparse
import json
import time

from .bench import stressng
from .environment import software as env_soft
from .environment import hardware as env_hw
from .tuning import setup as tuning_setup


def main():
    benchmarks = {"qsort": stressng.StressNG()}
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

    tuning_setup.Tuning().apply()
    env = env_soft.Environment().dump()
    hw = env_hw.Hardware().dump()
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
    main()
