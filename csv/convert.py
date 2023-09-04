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
    file_path = pathlib.Path(args.filename)
    data = json.loads(file_path.read_bytes())

    create_csv_benchmarks_cpu(output_file(file_path, "bench"), data)
    create_csv_power(output_file(file_path, "power"), data)
    create_csv_memory(output_file(file_path, "memory"), data)


def output_file(input_file: pathlib.Path, category: str) -> pathlib.Path:
    return input_file.parent / (f"{input_file.stem}.{category}.csv")


def create_csv_benchmarks_cpu(out_file: pathlib.Path, data):
    def ok_key(item):
        filtered = {"detail", "cpu_pin", "monitoring"}
        return item not in filtered

    with open(out_file, "w") as out:
        print(f"Writing cpu benchmark results to {out_file}")
        # use first result to print CSV header
        csv_keys = list(filter(ok_key, iter(data["bench"].values()).__next__().keys()))
        print(",".join(csv_keys), file=out)

        results = sorted(data["bench"].values(), key=result_key)

        for result in results:
            map(warn_new_key(csv_keys), result.items())
            # skip any missing 'bogo ops/s'
            if "bogo ops/s" not in result:
                continue
            values = [str(result[key]) for key in csv_keys]
            print(",".join(values), file=out)


def create_csv_power(out_file: pathlib.Path, data):
    with open(out_file, "w") as out:
        print(f"Writing power results to {out_file}")
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


def create_csv_memory(out_file: pathlib.Path, data):
    with open(out_file, "w") as out:
        print(f"Writing memory results to {out_file}")
        print("job_name,job_number,test,type,workers,speed", file=out)
        results = sorted(data["bench"].values(), key=result_key)
        # first stress-ng STREAM-like benchmark
        print_streams(out, results)
        # then stress-ng memrate benchmark
        print_memrates(out, results)


def print_streams(out, results):
    for result in results:
        engine_module = result.get("engine_module")
        if engine_module != "stream":
            continue
        job_name = result.get("job_name", "")
        job_number = result.get("job_number", "")
        workers = result.get("workers")
        total = result.get("sum_total")
        print(
            f"{job_name},{job_number},{engine_module},total,{workers},{total}", file=out
        )


def print_memrates(out, results):
    result_list = []
    for result in results:
        engine_module = result.get("engine_module")
        if engine_module != "memrate":
            continue
        job_name = result.get("job_name", "")
        job_number = result.get("job_number", "")
        workers = result.get("workers")
        for key in result.keys():
            if isinstance(result[key], dict) and "sum_speed" in result[key]:
                result_list.append(
                    {
                        "job_name": job_name,
                        "job_number": job_number,
                        "engine_module": engine_module,
                        "workers": workers,
                        "key": key,
                        "sum_speed": result[key]["sum_speed"],
                    }
                )

    def memrate_key(r):
        # custom sort order for memrate results using string concatenation
        return (
            r.get("job_name", "")
            + r.get("engine_module", "")
            + r.get("key", "")
            + f'{r.get("workers", ""):05}'
            + f'{r.get("job_number", ""):06}'
        )

    results_sorted = sorted(result_list, key=memrate_key)
    for r in results_sorted:
        print(
            f"{r['job_name']},{r['job_number']},{r['engine_module']},{r['key']},{r['workers']},{r['sum_speed']}",
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
