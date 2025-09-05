import numpy as np

from graph.graph import Graph
from hwbench.bench.monitoring_structs import Metrics, PowerCategories, PowerContext


def graph_sum_ratio(args, bench, bench_name, output_dir, time_serie, serie, base_outfile) -> int:
    # Render the ratio of power consumption
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        f"{args.title}\n\nRatio of power consumption during {bench_name} benchmark\n\n{bench.title()}",
        "Time [seconds]",
        "Percent of the whole server",
        output_dir,
        f"time_watt_percent_{base_outfile}_by_group",
    )

    # For each type metrics stored into the serie
    for component in serie:
        if len(serie[str(component)]) == 0:
            continue
        y_serie = np.array(serie[str(component)])[order]
        curve_label = f"{component!s}"
        graph.get_ax().plot(x_serie, y_serie, "", label=curve_label, marker=".")

    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, 5, 1),
        points_to_plot=len(serie[next(iter(serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render()
    return 1


def graph_sum_of_servers(args, bench, bench_name, output_dir, time_serie, serie, base_outfile) -> int:
    # Render sum_of_Servers
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        f"{args.title}\n\nSum of servers power consumption during {bench_name} benchmark\n\n{bench.title()}",
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}_by_group",
    )

    # For each type metrics stored into the serie
    for component in serie:
        if len(serie[str(component)]) == 0:
            continue
        y_serie = np.array(serie[str(component)])[order]
        curve_label = f"sum of {component!s}"
        graph.get_ax().plot(x_serie, y_serie, "", label=curve_label, marker=".")

    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, 1000, 500),
        points_to_plot=len(serie[next(iter(serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render()
    return 1


def graph_servers(args, bench, bench_name, output_dir, time_serie, serie, base_outfile) -> int:
    # Render Servers
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        f"{args.title}\n\nServers power consumption during {bench_name} benchmark\n\n{bench.title()}",
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}_by_servers",
    )

    for trace in args.traces:
        y_serie = np.array(serie[trace.get_name()])[order]
        graph.get_ax().plot(
            x_serie,
            y_serie,
            "",
            label=trace.get_name(),
            marker=".",
        )

    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, 50, 25),
        interval=bench.get_time_interval(),
    )
    graph.render()
    return 1


def graph_group_env(args, bench_name, output_dir) -> int:
    """Graph servers vs sum of the servers"""
    rendered_graphs = 0
    if args.verbose:
        print(f"group: working on {bench_name}")

    # As all benchmarks are known to be equivalent,
    # let's pick the first one as reference
    bench = args.traces[0].bench(bench_name)
    base_outfile = (
        f"{bench_name} {bench.workers()}x{bench.engine()}_{bench.engine_module()}_{bench.engine_module_parameter()}"
    )

    time_serie = []
    sum_server_serie = {}  # type: dict[str, list]
    sum_server_ratio = {}  # type: dict[str, list]
    server_serie = {}  # type: dict[str, list]

    for sample in range(0, bench.get_samples_count()):
        time = sample * bench.get_time_interval()
        time_serie.append(time)

        values = {}
        for context, category in [PowerContext.BMC, PowerCategories.SERVER], [PowerContext.CPU, "package"]:
            name = f"{str(context)}.{str(category)}"
            if name not in sum_server_serie:
                sum_server_serie[name] = []
            values[name] = 0

            for trace in args.traces:
                pc = trace.bench(bench_name).get_single_metric(Metrics.POWER_CONSUMPTION, context, category)

                if sample >= len(pc.get_mean()):
                    print(f"Warning: {trace.get_name()}/{bench_name}: Missing sample {sample}, considering 0 watts.")
                    server_power = 0
                else:
                    server_power = pc.get_mean()[sample]

                if trace.get_name() not in server_serie:
                    server_serie[trace.get_name()] = []

                if context == PowerContext.BMC:
                    server_serie[trace.get_name()].append(server_power)
                values[name] += server_power

            sum_server_serie[name].append(values[name])

    server_metric = f"{str(PowerContext.BMC)}.{str(PowerCategories.SERVER)}"
    package_metric = f"{str(PowerContext.CPU)}.package"
    delta_metric = f"({server_metric} - {package_metric})"
    sum_server_serie[delta_metric] = [
        sum_server_serie[server_metric][i] - sum_server_serie[package_metric][i]
        for i in range(len(sum_server_serie[server_metric]))
    ]

    sum_server_ratio[package_metric] = [
        sum_server_serie[package_metric][i] / float(sum_server_serie[server_metric][i]) * 100
        for i in range(len(sum_server_serie[server_metric]))
    ]
    sum_server_ratio[delta_metric] = [
        sum_server_serie[delta_metric][i] / float(sum_server_serie[server_metric][i]) * 100
        for i in range(len(sum_server_serie[server_metric]))
    ]

    rendered_graphs += graph_servers(args, bench, bench_name, output_dir, time_serie, server_serie, base_outfile)
    rendered_graphs += graph_sum_of_servers(
        args, bench, bench_name, output_dir, time_serie, sum_server_serie, base_outfile
    )
    rendered_graphs += graph_sum_ratio(args, bench, bench_name, output_dir, time_serie, sum_server_ratio, base_outfile)

    return rendered_graphs
