import math

import numpy as np

from graph.common import cdu_header, context_header, location_header
from graph.graph import MAX_LEGEND_ITEMS, Graph, draw_lines, get_max_value_string_length, statistics_in_label
from hwbench.bench.monitoring_structs import MonitoringContextKeys, PowerCategories, PowerConsumptionContextKeys


def statistics_labels(series: dict[str, np.ndarray]) -> dict[str, str]:
    """The labels of curves with their [min; mean; stddev; max], aligned on each other."""
    title_length = max(len(name) for name in series)
    value_length = max(get_max_value_string_length(serie) for serie in series.values())
    return {name: statistics_in_label(name, serie, title_length, value_length) for name, serie in series.items()}


def named_servers(series: dict[str, np.ndarray], capacity: int = MAX_LEGEND_ITEMS) -> tuple[list[str], list[str]]:
    """The servers named in the legend of the graph of the servers, a legend naming a fleet being longer
    than the graph: all of them when they fit in its capacity, as the first list. Otherwise the ones of
    the highest means, then the ones of the lowest, each by decreasing mean, filling the legend but a
    line telling how many servers are between them."""
    if len(series) <= capacity:
        return list(series), []
    by_mean = sorted(series, key=lambda name: np.mean(series[name]), reverse=True)
    room = max(2, capacity - 1)
    return by_mean[: (room + 1) // 2], by_mean[len(by_mean) - room // 2 :]


def round_step(top: float, max_ticks: int = 15) -> float:
    """The smallest round step, 1, 2, 2.5 or 5 times a power of ten, giving at most max_ticks ticks up to top."""
    if top <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(top / max_ticks))
    return next(step * power for step in (1, 2, 2.5, 5, 10) if top / (step * power) <= max_ticks)


def place_suffix(args) -> str:
    """The name of the place of a group of --auto-group in the file names of its graphs: '_Rack_A12'."""
    return f"_{args.place_name}" if getattr(args, "place_name", None) else ""


def graph_sum_ratio(args, bench, bench_name, output_dir, time_serie, serie, base_outfile) -> int:
    # Render the ratio of power consumption
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        f"{args.title}\n\nRatio of power consumption during {bench_name} benchmark{context_header(args)}{location_header(args)}{cdu_header(args)}\n\n{bench.title()}",
        "Time [seconds]",
        "Percent of the whole server",
        output_dir,
        f"time_watt_percent_{base_outfile}{place_suffix(args)}_by_group",
    )

    # For each type metrics stored into the serie
    series = {f"{component!s}": np.array(serie[str(component)])[order] for component in serie if serie[str(component)]}
    labels = statistics_labels(series) if series else {}
    for name, y_serie in series.items():
        graph.get_ax().plot(x_serie, y_serie, "", label=labels[name], marker=".")

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
        f"{args.title}\n\nSum of servers power consumption during {bench_name} benchmark{context_header(args)}{location_header(args)}{cdu_header(args)}\n\n{bench.title()}",
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}{place_suffix(args)}_by_group",
    )

    # For each type metrics stored into the serie
    series = {
        f"sum of {component!s}": np.array(serie[str(component)])[order] for component in serie if serie[str(component)]
    }
    labels = statistics_labels(series) if series else {}
    for name, y_serie in series.items():
        graph.get_ax().plot(x_serie, y_serie, "", label=labels[name], marker=".")

    # The axis keeps up to 15 ticks, as precise for a rack as for a whole site
    y_major = round_step(max((max(y_serie) for y_serie in series.values()), default=0))
    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, y_major, y_major / 2),
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
        f"{args.title}\n\nServers power consumption during {bench_name} benchmark{context_header(args)}{location_header(args)}{cdu_header(args)}\n\n{bench.title()}",
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}{place_suffix(args)}_by_servers",
    )

    series = {trace.get_name(): np.array(serie[trace.get_name()])[order] for trace in args.traces}
    highest, lowest = named_servers(series)
    labels = statistics_labels({name: series[name] for name in highest + lowest})
    for name in highest:
        graph.get_ax().plot(x_serie, series[name], "", label=labels[name], marker=".")
    if lowest:
        # The legend gives the highest means, the number of servers between them and the lowest means
        others = [name for name in series if name not in labels]
        graph.get_ax().plot([], [], " ", label=f"… {len(others)} other servers between")
        for name in lowest:
            graph.get_ax().plot(x_serie, series[name], "", label=labels[name], marker=".")
        draw_lines(graph.get_ax(), x_serie, [series[name] for name in others])

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

    # Loading a benchmark parses all its monitoring: once per trace, not once per sample
    benches = {trace.get_name(): trace.bench(bench_name) for trace in args.traces}
    for sample in range(0, bench.get_samples_count()):
        time = sample * bench.get_time_interval()
        time_serie.append(time)

        values = {}
        for context, category in (
            [PowerConsumptionContextKeys.BMC, PowerCategories.SERVER],
            [PowerConsumptionContextKeys.CPU, "package"],
        ):
            name = f"{str(context)}.{str(category)}"
            if name not in sum_server_serie:
                sum_server_serie[name] = []
            values[name] = 0

            for trace in args.traces:
                pc = benches[trace.get_name()].get_single_metric(
                    MonitoringContextKeys.PowerConsumption, context, category
                )

                if sample >= len(pc.get_mean()):
                    print(f"Warning: {trace.get_name()}/{bench_name}: Missing sample {sample}, considering 0 watts.")
                    server_power = 0
                else:
                    server_power = pc.get_mean()[sample]

                if trace.get_name() not in server_serie:
                    server_serie[trace.get_name()] = []

                if context == PowerConsumptionContextKeys.BMC:
                    server_serie[trace.get_name()].append(server_power)
                values[name] += server_power

            sum_server_serie[name].append(values[name])

    server_metric = f"{PowerConsumptionContextKeys.BMC}.{PowerCategories.SERVER}"
    package_metric = f"{PowerConsumptionContextKeys.CPU}.package"
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
