#!/usr/bin/env python3

import argparse
import json
import sys
import pathlib


def main():
    parser = argparse.ArgumentParser(
        prog="convert",
        description="Convert hwbench results to csv",
    )
    parser.add_argument("filename", help="input JSON file to convert to CSV")
    args = parser.parse_args()
    data = json.load(open(args.filename, "r"))

    print_csv_benchmarks_cpu(data)

    create_csv_power(pathlib.Path(args.filename).stem + "-monitoring.csv", data)


def print_csv_benchmarks_cpu(data):
    def ok_key(item):
        filtered = {"detail", "cpu_pin", "monitoring"}
        return item not in filtered

    # use first result to print CSV header
    csv_keys = list(filter(ok_key, iter(data["bench"].values()).__next__().keys()))
    print(",".join(csv_keys))

    results = sorted(data["bench"].values(), key=result_key)

    for result in results:
        map(warn_new_key(csv_keys), result.items())
        values = [str(result[key]) for key in csv_keys]
        print(",".join(values))


def create_csv_power(out_file_name: str, data):
    with open(out_file_name, "w") as out:
        print("job_name,job_number,category,type,unit,event", file=out)
        results = sorted(data["bench"].values(), key=result_key)
        for result in results:
            job_name = result.get("job_name", "")
            job_number = result.get("job_number", "")
            monitoring = result.get("monitoring", {})
            for category in monitoring.keys():
                for typ in monitoring[category].keys():
                    measures = monitoring[category][typ]
                    events = measures.get("events", [])
                    unit = measures.get("unit")
                    if not unit:
                        continue
                    for event in events:
                        print(
                            f"{job_name},{job_number},{category},{typ},{unit},{event}",
                            file=out,
                        )


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


def warn_new_key(csv_keys):
    return lambda item: item[0] not in csv_keys and print(
        f"Unknown key {item[0]}", file=sys.stderr
    )


if __name__ == "__main__":
    main()
