#!/usr/bin/env python3

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="convert",
        description="Convert hwbench results to csv",
    )
    parser.add_argument("filename", help="input JSON file to convert to CSV")
    args = parser.parse_args()
    data = json.load(open(args.filename, "r"))

    def ok_key(item):
        filtered = {"detail", "cpu_pin", "monitoring"}
        return item not in filtered

    # use first result to print CSV header
    csv_keys = list(filter(ok_key, iter(data["bench"].values()).__next__().keys()))
    print(",".join(csv_keys))

    def warn_new_key(item):
        if item[0] not in csv_keys:
            print(f"Unknown key {item[0]}", file=sys.stderr)

    def result_key(r):
        # custom sort order for results using string concatenation
        return (
            r.get("engine", "")
            + r.get("engine_module", "")
            + r.get("engine_module_parameter", "")
            + r.get("job_name", "")
            + f'{r.get("workers", ""):05}'
            + f'{r.get("job_number", "")}'
        )

    results = sorted(data["bench"].values(), key=result_key)

    for result in results:
        map(warn_new_key, result.items())
        values = [str(result[key]) for key in csv_keys]
        print(",".join(values))


if __name__ == "__main__":
    main()
