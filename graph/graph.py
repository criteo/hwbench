#!/usr/bin/env python3
import argparse
import glob
import json
import os
import pathlib
import shutil
import sys
from subprocess import check_output

MIN = "min"
MAX = "max"
MEAN = "mean"
EVENTS = "events"
UNIT = "unit"


def fatal(reason):
    """Print the error and exit 1."""
    sys.stderr.write("Fatal: {}\n".format(reason))
    sys.stderr.flush()
    sys.exit(1)


def get_monitoring(bench):
    """Return the monitoring of a given benchmark."""
    return bench.get("monitoring")


def get_min(component):
    """Return the min data structure of a component."""
    return component[MIN]


def get_mean(component):
    """Return the mean data structure of a component."""
    return component[MEAN]


def get_max(component):
    """Return the max data structure of a component."""
    return component[MAX]


def get_min_events(component):
    """Return the min serie of a component."""
    return get_min(component).get(EVENTS)


def get_mean_events(component):
    """Return the mean serie of a component."""
    return get_mean(component).get(EVENTS)


def get_max_events(component):
    """Return the max serie of a component."""
    return get_max(component).get(EVENTS)


def get_samples_count(component):
    """Return the number of monitoring samples."""
    return len(get_min_events(component))


def get_duration(bench):
    """Return the duration of a benchmark."""
    return bench["timeout"]


def render(
    args,
    gnuplot_file,
    output_file,
    subtitle,
    system_title,
    unit,
    bench_name,
    bench_data,
):
    """Render the a gnuplot file"""
    xaxis = get_duration(bench_data)
    title = (
        f'{gstr(args.title)}\n\n{subtitle} during "{gstr(bench_name)}" benchmark\n'
        f"\n{get_bench_title(bench_data)}\n{system_title}"
    )
    check_output(
        [
            f"gnuplot -c {gnuplot_file} '{str(output_file.name)}' '{title}' '{unit}' "
            f"'{xaxis}' '{str(output_file.name).replace('.dat','')}'"
        ],
        shell=True,
    ).decode()
    # Move all generated png files into a specific directory
    png_dir = pathlib.Path(f"{out_directory(args)}/{bench_name}/png")
    png_dir.mkdir(parents=True, exist_ok=True)
    for file in glob.glob(f"{out_directory(args)}/{bench_name}/*.png"):
        shutil.move(file, os.path.join(png_dir, os.path.basename(file)))


def yerr_graph(
    args,
    output_dir,
    time_interval,
    subtitle,
    system_title,
    bench_name,
    bench_data,
    gnuplot_file,
    unit,
    component_name,
    component,
):
    """Generates error bar graph."""
    output_file = open(
        f"{output_dir}/{component_name}.dat",
        "w",
    )
    for sample in range(0, get_samples_count(component)):
        time = sample * time_interval
        min = get_min_events(component)[sample]
        max = get_max_events(component)[sample]
        mean = get_mean_events(component)[sample]
        print(f"{time} {mean} {min} {max}", file=output_file)
    output_file.close()
    render(
        args,
        f"{gnuplot_file}.gnuplot",
        output_file,
        subtitle,
        system_title,
        unit,
        bench_name,
        bench_data,
    )


def gstr(mystr):
    """Prepare a string for being printed in gnuplot."""
    # _ are used in gnuplot to make indexes, let's replace them.
    return str(mystr).replace("_", "-")


def get_system_title(bench_data):
    """Prepare the graph system title."""
    d = bench_data.get("hardware").get("dmi")
    c = bench_data.get("hardware").get("cpu")
    k = bench_data.get("environment").get("kernel")
    title = (
        f"System: {gstr(d['serial'])} {gstr(d['product'])} Bios "
        f"v{gstr(d['bios']['version'])} Linux Kernel {gstr(k['release'])}"
    )
    title += (
        f"\nProcessor: {gstr(c['model'])} with {gstr(c['physical_cores'])} cores "
        f"and {gstr(c['numa_domains'])} NUMA domains"
    )
    return title


def get_bench_title(bench):
    """Prepare the benchmark title name."""
    title = f"Stressor: {bench['workers']} x {gstr(bench['engine'])} "
    title += f"{gstr(bench['engine_module'])} "
    title += f"{gstr(bench['engine_module_parameter'])} for {bench['timeout']} seconds"
    return title


def get_components(bench_data, component_name):
    """Return the list of components of a benchmark."""
    return [
        key
        for key, _ in get_monitoring(bench_data).items()
        if component_name in key.lower()
    ]


def get_components_by_unit(bench_data, unit):
    """Return the list of components of a benchmark."""
    return [
        key
        for key, value in get_monitoring(bench_data).items()
        if unit in value["min"]["unit"].lower()
    ]


def generic_graph(
    args,
    system_title,
    bench_name,
    bench_data,
    name,
    component_name,
    item_title,
    gnuplot_file,
    power=True,
    thermal=False,
):
    """Graph an undefined number of metrics of the same type against power or thermal"""
    monitoring = get_monitoring(bench_data)
    if component_name == "temp":
        components = get_components_by_unit(bench_data, "celsius")
    else:
        components = get_components(bench_data, component_name)
    if not components:
        print(f"{bench_name}: no {name}")
        return

    thermal_components = get_components_by_unit(bench_data, "celsius")
    samples_count = get_samples_count(monitoring[components[0]])
    unit = get_min(monitoring[components[0]]).get(UNIT)

    print(
        f"{bench_name}: {len(components)} {name} to graph with {samples_count} samples"
    )
    time_interval = 10  # Hardcoded for now in benchmark.py
    output_dir = pathlib.Path(f"{out_directory(args)}{bench_name}")
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    # Graphing all components at once
    # Let's first prepare the gnuplot file
    orig_file = pathlib.Path(gnuplot_file)
    dest_file = pathlib.Path(f"{output_dir}/{gnuplot_file}")
    shutil.copyfile(orig_file, dest_file)
    output_file = open(
        f"{dest_file}",
        "a",
    )

    # Each component a specific plot instruction
    plot_string = ""
    for component_number in range(0, len(components)):
        if component_number == 0:
            plot_string = (
                f"plot ARG1 using 1:{component_number+2} title "
                f"'{gstr(components[component_number])}' with lines"
            )
        else:
            plot_string += (
                f",\\\n ARG1 using 1:{component_number+2} title "
                f"'{gstr(components[component_number])}' with lines"
            )
    # If we need to render power on y2 avis
    if power:
        plot_string += (
            f",\\\n ARG1 using 1:{component_number+3} title "
            f"'Enclosure Power' axes x2y2 with linespoint"
        )
        plot_string += (
            f",\\\n ARG1 using 1:{component_number+4} title "
            f"'Chassis Power' axes x2y2 with linespoint"
        )
    elif thermal:  # or thermal on y2 axis
        index = component_number + 2
        for thermal_component in thermal_components:
            index += 1
            plot_string += (
                f",\\\n ARG1 using 1:{index} title "
                f"'{gstr(thermal_component)}' axes x2y2 with linespoint"
            )
    print(f"{plot_string}", file=output_file)
    output_file.close()

    # Let's report all the mean fan metrics per time at once
    output_file = open(
        f"{output_dir}/{name.replace(' ','_')}.dat",
        "w",
    )
    for sample in range(0, samples_count):
        time = sample * time_interval
        value = f"{time}"
        # Collect all components mean value
        for component in components:
            value += f" {get_mean_events(monitoring[component])[sample]}"
        # Add power or thermal if needed on y2 axis
        if power:
            value += f" {get_mean_events(monitoring['enclosure'])[sample]}"
            value += f" {get_mean_events(monitoring['chassis'])[sample]}"
        elif thermal:
            # Let's add all thermal components
            for thermal_component in thermal_components:
                value += f" {get_mean_events(monitoring[thermal_component])[sample]}"
        print(f"{value}", file=output_file)
    output_file.close()
    render(
        args,
        f"{dest_file}",
        output_file,
        item_title,
        system_title,
        unit,
        bench_name,
        bench_data,
    )


def graph_fans(args, system_title, bench_name, bench_data):
    """Graph all fans."""
    monitoring = get_monitoring(bench_data)
    fans = get_components(bench_data, "fan")
    if not fans:
        print(f"{bench_name}: no fans")
        return
    # Graph all fans versus power
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "fans_power",
        "fan",
        "Fans speed",
        "Fans_power.gnuplot",
    )
    # Graph all fans versus thermal
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "fans_thermal",
        "fan",
        "Fans speed",
        "Fans_thermal.gnuplot",
        power=False,
        thermal=True,
    )

    # Graphing individual fans with error bars
    time_interval = 10  # Hardcoded for now in benchmark.py
    unit = get_min(monitoring[fans[0]]).get(UNIT)
    output_dir = pathlib.Path(f"{out_directory(args)}/{bench_name}")
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    for fan in fans:
        subtitle = "{/:Bold {}" + fan + " speed}"
        yerr_graph(
            args,
            output_dir,
            time_interval,
            subtitle,
            system_title,
            bench_name,
            bench_data,
            "Fan",
            unit,
            fan,
            monitoring.get(fan),
        )


def graph_cpu(args, system_title, bench_name, bench_data):
    """Graph all CPU graphs."""
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "cpu cores",
        "watt_core",
        "Core power consumption",
        "Cores.gnuplot",
    )
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "package",
        "package",
        "Package power consumption",
        "Package.gnuplot",
    )
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "frequency_power",
        "mhz",
        "Core frequency",
        "Frequency.gnuplot",
    )
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "frequency_thermal",
        "mhz",
        "Core frequency",
        "Frequency_thermal.gnuplot",
        power=False,
        thermal=True,
    )


def graph_temp(args, system_title, bench_name, bench_data):
    """Graph all temperature graphs."""
    generic_graph(
        args,
        system_title,
        bench_name,
        bench_data,
        "temperature",
        "temp",
        "Temperatures",
        "Temperatures.gnuplot",
        power=False,
    )


def plot_bench(args, system_title, bench_name, bench_data):
    """Graph all graphs."""
    graph_fans(args, system_title, bench_name, bench_data)
    graph_cpu(args, system_title, bench_name, bench_data)
    graph_temp(args, system_title, bench_name, bench_data)


def out_directory(args):
    """Determine the name of the output directory."""
    return f"{args.filename.replace('.json', '')}_out/"


def main():
    parser = argparse.ArgumentParser(
        prog="graph",
        description="graph hwbench results to csv",
    )
    parser.add_argument("filename", help="input JSON file to convert to graph")
    parser.add_argument("--title", help="Title of the graph")

    args = parser.parse_args()
    file_path = pathlib.Path(args.filename)
    data = json.loads(file_path.read_bytes())
    benches = data.get("bench")
    if not benches:
        fatal("Missing bench data structure in {args.filename}")

    # Generate graphs for each benchmark
    for bench in benches:
        plot_bench(args, get_system_title(data), bench, benches.get(bench))

    print(f"Results can be found in {out_directory(args)} directory")


main()
