import numpy as np
from graph.graph import Graph


def graph_enclosure(args, bench_name, output_dir) -> int:
    """Graph enclosure vs sum of the chassis"""
    if args.verbose:
        print(f"enclosure: working on {bench_name}")

    outdir = output_dir.joinpath("enclosure")

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)
    base_outfile = f"{bench_name} {bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}_enclosure"
    y_label = "Watts"
    title = (
        f'{args.title}\n\nEnclosure power consumption during "{bench_name}" benchmark\n'
        f"\n{bench.title()}"
    )

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        y_label,
        outdir,
        f"time_watt_{base_outfile}",
    )

    time_interval = 10  # Hardcoded for now in benchmark.py
    time_serie = []
    sum_serie = {}  # type: dict[str, list]
    chassis_serie = {}  # type: dict[str, list]
    components = ["chassis", "enclosure", "infrastructure"]
    samples_count = bench.get_samples_count("chassis")
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            # Not all components are available on every system
            if component not in bench.get_monitoring():
                continue

            if component not in sum_serie:
                sum_serie[component] = []

            # We want to get the sum of chassis vs enclosure
            if component == "chassis":
                value = 0
                # so let's add all chassis's value from each trace
                for trace in args.traces:
                    chassis_power = trace.bench(bench_name).get_mean_events(component)[
                        sample
                    ]
                    if trace.get_name() not in chassis_serie:
                        chassis_serie[trace.get_name()] = []
                    chassis_serie[trace.get_name()].append(chassis_power)
                    value += chassis_power
            else:
                value = bench.get_mean_events(component)[sample]
            sum_serie[component].append(value)
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    for component in components:
        y_serie = np.array(sum_serie[component])[order]
        curve_label = component
        if component == "chassis":
            curve_label = "sum of chassis"
        graph.get_ax().plot(x_serie, y_serie, "", label=curve_label)

    for trace in args.traces:
        y_serie = np.array(chassis_serie[trace.get_name()])[order]
        graph.get_ax().plot(x_serie, y_serie, "", label=trace.get_name())

    graph.prepare_axes(
        30,
        15,
        (None, 50, 25),
    )
    graph.render()

    return 1
