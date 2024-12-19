import numpy as np
from graph.graph import Graph
from hwbench.bench.monitoring_structs import Metrics, PowerCategories, PowerContext


def graph_chassis(args, bench_name, output_dir) -> int:
    """Graph chassis vs sum of the servers"""
    if args.verbose:
        print(f"chassis: working on {bench_name}")

    outdir = output_dir.joinpath("chassis")

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)
    base_outfile = f"{bench_name} {bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}_chassis"
    y_label = "Watts"
    title = f"{args.title}\n\nChassis power consumption during {bench_name} benchmark\n\n{bench.title()}"

    def get_marker(category: PowerCategories) -> str:
        if category == PowerCategories.SERVER:
            return "x"  # cross
        if category == PowerCategories.SERVERINCHASSIS:
            return "o"  # circle
        return ""

    time_serie = []
    sum_serie = {}  # type: dict[str, list]
    sum_serie_in_chassis = {}  # type: dict[str, list]
    server_serie = {}  # type: dict[str, list]
    serverinchassis_serie = {}  # type: dict[str, list]
    for sample in range(0, bench.get_samples_count()):
        time = sample * bench.get_time_interval()
        time_serie.append(time)
        # Collect all components mean value
        for component in PowerCategories.list():
            # Not all components are available on every system
            if component not in bench.get_component(Metrics.POWER_CONSUMPTION, PowerContext.BMC):
                continue

            if str(component) not in sum_serie:
                sum_serie[str(component)] = []
                sum_serie_in_chassis[str(component)] = []
                sum_serie[str(Metrics.POWER_SUPPLIES)] = []
                sum_serie_in_chassis[str(Metrics.POWER_SUPPLIES)] = []

            value = 0
            # We want to get the sum of servers/serversinchassis vs chassis
            if component in [PowerCategories.SERVER, PowerCategories.SERVERINCHASSIS]:
                # so let's add all server's value from each trace
                for trace in args.traces:
                    pc = trace.bench(bench_name).get_single_metric(
                        Metrics.POWER_CONSUMPTION, PowerContext.BMC, component
                    )
                    if sample >= len(pc.get_mean()):
                        print(
                            f"Warning: {trace.get_name()}/{bench_name}: Missing sample {sample}, considering 0 watts."
                        )
                        server_power = 0
                    else:
                        server_power = pc.get_mean()[sample]

                    if trace.get_name() not in server_serie:
                        server_serie[trace.get_name()] = []
                        serverinchassis_serie[trace.get_name()] = []

                    # Split the series per SERVER or SERVERINCHASSIS
                    if component == PowerCategories.SERVER:
                        server_serie[trace.get_name()].append(server_power)
                    else:
                        serverinchassis_serie[trace.get_name()].append(server_power)
                    value += server_power

                if component == PowerCategories.SERVER:
                    sum_serie[str(component)].append(value)
                else:
                    sum_serie_in_chassis[str(component)].append(value)
            else:
                # These are shared metrics on the chassis, so picking one from the first bench
                # should be enough to get the chassis metric, no need to iterate on traces.
                value = bench.get_single_metric(Metrics.POWER_CONSUMPTION, PowerContext.BMC, component).get_mean()[
                    sample
                ]
                sum_serie[str(component)].append(value)
                sum_serie_in_chassis[str(component)].append(value)

            # Let's add the PSUs
            psus = bench.get_psu_power()
            if psus:
                sum_serie[str(Metrics.POWER_SUPPLIES)].append(psus[sample])
                sum_serie_in_chassis[str(Metrics.POWER_SUPPLIES)].append(psus[sample])

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]

    # Let's plot two different graphs, one by SERVER, one by SERVERINCHASSIS
    graphs_to_plot = [PowerCategories.SERVER]
    if len(serverinchassis_serie) > 0:
        graphs_to_plot.append(PowerCategories.SERVERINCHASSIS)

    # Let's iterate to plot the two types of graph
    for graph_type in graphs_to_plot:
        graph = Graph(
            args,
            title,
            "Time [seconds]",
            y_label,
            outdir,
            f"time_watt_{base_outfile}_by_{str(graph_type)}",
        )

        if graph_type == PowerCategories.SERVERINCHASSIS:
            serie = serverinchassis_serie
            sum_serie_to_plot = sum_serie_in_chassis
            label_caption = " (in chassis)"
        else:
            serie = server_serie
            sum_serie_to_plot = sum_serie
            label_caption = ""

        # For each type metrics stored into the serie
        for component in sum_serie_to_plot:
            if len(sum_serie_to_plot[str(component)]) == 0:
                continue
            y_serie = np.array(sum_serie_to_plot[str(component)])[order]
            curve_label = str(component)
            if component in [PowerCategories.SERVER, PowerCategories.SERVERINCHASSIS]:
                curve_label = f"sum of {str(component)}"
            graph.get_ax().plot(x_serie, y_serie, "", label=curve_label, marker=get_marker(component))

        for trace in args.traces:
            y_serie = np.array(serie[trace.get_name()])[order]
            graph.get_ax().plot(
                x_serie,
                y_serie,
                "",
                label=trace.get_name() + label_caption,
                marker=get_marker(graph_type),
            )

        graph.prepare_axes(
            3 * bench.get_time_interval(),
            bench.get_time_interval(),
            (None, 50, 25),
            points_to_plot=len(sum_serie_to_plot[next(iter(sum_serie_to_plot))]),
            interval=bench.get_time_interval(),
        )
        graph.render()

    return len(graphs_to_plot)
