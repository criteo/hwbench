#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import time

from .bench import stressng, bench
from .environment import software as env_soft
from .environment import hardware as env_hw
from .utils import helpers as h
from .tuning import setup as tuning_setup

Benchmarks = dict[str, bench.Bench]


def main():
    if not is_root():
        h.fatal("hwbench is not running as effective uid 0.")

    out_dir, tuning_out_dir = create_output_directory()
    benchmarks = build_benchmarks(out_dir)
    args = parse_options(list(benchmarks.keys()))

    tuning_setup.Tuning(tuning_out_dir).apply()
    env = env_soft.Environment(out_dir).dump()
    hw = env_hw.Hardware(out_dir).dump()

    results = run_benchmarks(benchmarks, args.bench)

    out = format_output(env, hw, results)

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


def build_benchmarks(out_dir: pathlib.Path) -> Benchmarks:
    nproc = os.sysconf("SC_NPROCESSORS_ONLN")
    # stressng --stream only works with at least 5s
    run_secs = 10
    cpu_benches = stressng.stress_ng_cpu_all(out_dir, run_secs, nproc)
    other_benches = {
        "qsort": stressng.StressNGQsort(out_dir, run_secs, nproc),
        "stream": stressng.StressNGStream(out_dir, run_secs, nproc),
    }
    cpu_benches.update(other_benches)
    return cpu_benches


def parse_options(benchmark_names: list[str]):
    parser = argparse.ArgumentParser(
        prog="hwbench",
        description="Criteo Hardware Benchmarking tool",
    )
    parser.add_argument(
        "-b",
        "--bench",
        help="Specify which benchmark(s) to run",
        nargs="*",
        choices=benchmark_names,
        default=benchmark_names[0:1],
    )
    return parser.parse_args()


def run_benchmarks(benchmarks: Benchmarks, benchs: list[str]):
    results = {}
    for b in benchs:
        results[b] = benchmarks[b].run()

    return results


def format_output(env, hw, results) -> dict[str, object]:
    return {
        "environment": env,
        "hardware": hw,
        "bench": results,
    }


def write_output(out_dir: pathlib.Path, out):
    print(json.dumps(out, indent=4))
    (out_dir / "results.json").write_text(json.dumps(out))


if __name__ == "__main__":
    # don't add anything here setup.py points at main()
    main()
