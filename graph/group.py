import math

import numpy as np

from graph.auto_group import liquid_cooled
from graph.common import bench_workers, datapoint, graph_header
from graph.graph import (
    MAX_LEGEND_ITEMS,
    WINDOW_STATISTICS_LEGEND,
    Graph,
    draw_lines,
    get_max_value_string_length,
    plot_windows,
    window_statistics_in_label,
)
from hwbench.bench.monitoring_structs import MonitoringContextKeys, PowerCategories, PowerConsumptionContextKeys

# The curves of the power of the servers taken away by the air of the room and by a liquid, each always in
# the same color: the liquid blue, the air orange, the whole server neither
SERVER_POWER = "Total power consumption"
AIR_COOLED = "Total power to the air"
LIQUID_COOLED = "Total power to the liquid"
COLORS = {LIQUID_COOLED: "tab:blue", AIR_COOLED: "tab:orange", SERVER_POWER: "tab:green"}
# What the curves of the distribution of the power consumption add up, below the graphs
COOLING_NOTE = (
    f"{SERVER_POWER}: the sum of the {PowerConsumptionContextKeys.BMC}.{PowerCategories.SERVER} of the servers.\n"
    f"{LIQUID_COOLED}: the sum of the power of the components the topology says cooled by a liquid,\n"
    "    CPU.package for the CPUs, CPU.Ram or else BMC.Memory for the memory, the GPUs.\n"
    f"{AIR_COOLED}: the {SERVER_POWER.lower()} minus the {LIQUID_COOLED.lower()}, every component not cooled\n"
    "    by a liquid included, measured or not: the disks, the controllers, the fans..."
)


def cooling_note(graph):
    """The note below a graph of the distribution of the power consumption, telling what its curves add up,
    for render(): below the label of the x axis, whatever the height of its ticks."""
    return graph.get_ax().annotate(
        COOLING_NOTE,
        xy=(0, 0),
        xycoords=("axes fraction", graph.get_ax().xaxis.label),
        xytext=(0, -10),
        textcoords="offset points",
        va="top",
        fontsize=9,
    )


def statistics_labels(series: dict[str, np.ndarray]) -> dict[str, str]:
    """The labels of curves over time with their [p5; mean; stddev; p95], aligned on each other."""
    title_length = max(len(name) for name in series)
    value_length = max(get_max_value_string_length(serie) for serie in series.values())
    return {name: window_statistics_in_label(name, serie, title_length, value_length) for name, serie in series.items()}


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


def graph_sum_ratio(args, bench, bench_name, output_dir, time_serie, serie, base_outfile, workers: list[int]) -> int:
    # Render the ratio of power consumption
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        graph_header(args, "Distribution of the power consumption", bench_name, bench, workers),
        "Time [seconds]",
        "Percent of the total power consumption",
        output_dir,
        f"time_watt_percent_{base_outfile}{place_suffix(args)}_by_group",
        legend_title=WINDOW_STATISTICS_LEGEND,
    )

    # For each type metrics stored into the serie
    series = {f"{component!s}": np.array(serie[str(component)])[order] for component in serie if serie[str(component)]}
    labels = statistics_labels(series) if series else {}
    for name, y_serie in series.items():
        plot_windows(graph.get_ax(), x_serie, y_serie, "", label=labels[name], marker=".", color=COLORS.get(name))

    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, 5, 1),
        points_to_plot=len(serie[next(iter(serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render(extra_legend=[cooling_note(graph)])
    return 1


def graph_sum_of_servers(
    args, bench, bench_name, output_dir, time_serie, serie, base_outfile, workers: list[int]
) -> int:
    # Render sum_of_Servers
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        graph_header(args, "Distribution of the power consumption", bench_name, bench, workers),
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}{place_suffix(args)}_by_group",
        legend_title=WINDOW_STATISTICS_LEGEND,
    )

    # For each type metrics stored into the serie
    series = {str(component): np.array(serie[str(component)])[order] for component in serie if serie[str(component)]}
    labels = statistics_labels(series) if series else {}
    for name, y_serie in series.items():
        plot_windows(graph.get_ax(), x_serie, y_serie, "", label=labels[name], marker=".", color=COLORS.get(name))

    # The axis keeps up to 15 ticks, as precise for a rack as for a whole site
    y_major = round_step(max((max(y_serie) for y_serie in series.values()), default=0))
    graph.prepare_axes(
        3 * bench.get_time_interval(),
        bench.get_time_interval(),
        (None, y_major, y_major / 2),
        points_to_plot=len(serie[next(iter(serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render(extra_legend=[cooling_note(graph)])
    return 1


def graph_servers(args, bench, bench_name, output_dir, time_serie, serie, base_outfile, workers: list[int]) -> int:
    # Render Servers
    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    graph = Graph(
        args,
        graph_header(args, "Servers power consumption", bench_name, bench, workers),
        "Time [seconds]",
        "Watts",
        output_dir,
        f"time_watt_{base_outfile}{place_suffix(args)}_by_servers",
        legend_title=WINDOW_STATISTICS_LEGEND,
    )

    series = {trace.get_name(): np.array(serie[trace.get_name()])[order] for trace in args.traces}
    highest, lowest = named_servers(series)
    labels = statistics_labels({name: series[name] for name in highest + lowest})
    for name in highest:
        plot_windows(graph.get_ax(), x_serie, series[name], "", label=labels[name], marker=".")
    if lowest:
        # The legend gives the highest means, the number of servers between them and the lowest means
        others = [name for name in series if name not in labels]
        graph.get_ax().plot([], [], " ", label=f"… {len(others)} other servers between")
        for name in lowest:
            plot_windows(graph.get_ax(), x_serie, series[name], "", label=labels[name], marker=".")
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
    # The name of the benchmark only: the workers of the first server do not tell the ones of the others
    base_outfile = bench_name

    time_serie = []
    server_serie = {}  # type: dict[str, list]

    # Loading a benchmark parses all its monitoring: once per trace, not once per sample
    benches = {trace.get_name(): trace.bench(bench_name) for trace in args.traces}
    # The power of the components each server cools by a liquid, as its topology gives them, checked
    # before rendering, see hwgraph.py
    liquid = {
        trace.get_name(): liquid_cooled(benches[trace.get_name()], trace.get_cooling())[0] for trace in args.traces
    }
    server_metric, air_metric, liquid_metric = SERVER_POWER, AIR_COOLED, LIQUID_COOLED
    sum_server_serie = {server_metric: [], air_metric: [], liquid_metric: []}  # type: dict[str, list]
    for sample in range(0, bench.get_samples_count()):
        time_serie.append(sample * bench.get_time_interval())
        server_sum = liquid_sum = 0.0
        for trace in args.traces:
            name = trace.get_name()
            pc = benches[name].get_single_metric(
                MonitoringContextKeys.PowerConsumption, PowerConsumptionContextKeys.BMC, PowerCategories.SERVER
            )
            server_power = datapoint(args, pc.get_mean(), sample, f"{name}/{bench_name}")
            server_serie.setdefault(name, []).append(server_power)
            server_sum += server_power
            for metrics in liquid[name].values():
                liquid_sum += sum(
                    datapoint(args, metric.get_mean(), sample, f"{name}/{bench_name}") for metric in metrics
                )
        sum_server_serie[server_metric].append(server_sum)
        # What the liquid does not take away goes to the air of the room
        sum_server_serie[air_metric].append(server_sum - liquid_sum)
        sum_server_serie[liquid_metric].append(liquid_sum)

    sum_server_ratio = {
        metric: [
            value / server * 100 if server else 0.0
            for value, server in zip(sum_server_serie[metric], sum_server_serie[server_metric])
        ]
        for metric in (air_metric, liquid_metric)
    }

    workers = bench_workers(list(benches.values()))
    rendered_graphs += graph_servers(
        args, bench, bench_name, output_dir, time_serie, server_serie, base_outfile, workers
    )
    rendered_graphs += graph_sum_of_servers(
        args, bench, bench_name, output_dir, time_serie, sum_server_serie, base_outfile, workers
    )
    rendered_graphs += graph_sum_ratio(
        args, bench, bench_name, output_dir, time_serie, sum_server_ratio, base_outfile, workers
    )

    return rendered_graphs
