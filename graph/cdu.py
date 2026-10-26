from __future__ import annotations

from collections import defaultdict
from typing import TypeAlias
from urllib.parse import quote

import numpy as np

from graph.common import context_header
from graph.graph import MARKER_SIZE, Graph, curve_style, statistics_in_label, zero_margin
from graph.trace import Trace
from hwbench.bench.monitoring_structs import GPU_FAMILY

NamedSeries: TypeAlias = tuple[str, list[float]]
WINDOW_MEAN_LEGEND = "component [min; mean; stddev; max]\nof window means\n"


TITLES = {
    "Celsius": "Temperatures",
    "raw": "Raw readings",
    "L/min": "Flow rates",
    "Percent": "Percentage readings",
    "RPM": "Rotational speeds",
}


def cdu_series(data: dict, iteration_time: float) -> dict[str, list[tuple[str, list[float], list[float]]]]:
    """Group window means by unit on the shared host monitoring grid."""
    groups = defaultdict(list)
    for key, definition in data["metrics"].items():
        values = data["readings"][key]["mean"]
        readings = [np.nan if value is None else value for value in values]
        times = [index * iteration_time for index in range(len(values))]
        groups[definition["unit"]].append((definition["name"], times, readings))
    return dict(groups)


def graph_cdu(args, trace: Trace, bench_name: str, output_dir) -> int:
    bench = trace.bench(bench_name)
    # A benchmark run without monitoring, monitoring=none, has none
    monitoring = bench.get("monitoring") or {}
    cdus = monitoring.get("cdus", {})
    count = 0
    for index, (name, data) in enumerate(cdus.items()):
        metadata = monitoring["metadata"]
        if not metadata["samples_count"]:
            continue
        directory = output_dir / trace.get_name() / bench_name / "CDU" / f"{index}-{quote(name, safe='')}"
        groups = cdu_series(data, metadata["iteration_time"])
        for unit, series in groups.items():
            title = TITLES.get(unit, unit)
            graph = Graph(
                args,
                f'CDU {name}: {title} during "{bench.get_bench_name()}" benchmark job'
                f"{context_header(args)}\n{args.title}\n{bench.get_system_title()}",
                "Time [seconds]",
                unit,
                directory,
                quote(title, safe=" "),
                show_source_file=trace,
                legend_title=WINDOW_MEAN_LEGEND,
            )
            for label, timestamps, values in series:
                valid = np.array(values)[np.isfinite(values)]
                legend = statistics_in_label(label, valid) if len(valid) else f"{label} [no readings]"
                graph.get_ax().plot(timestamps, values, marker=".", label=legend)
            graph.prepare_axes(30, 5, points_to_plot=metadata["samples_count"], interval=metadata["iteration_time"])
            # A failure at either end must not shorten the visible benchmark period.
            graph.get_ax().set_xlim(0, max(1, bench.duration()))
            graph.get_ax().set_xlim(left=zero_margin(graph.get_ax().xaxis, max(1, bench.duration())))
            graph.render()
            count += 1
        for unit in VS_THERMAL:
            count += graph_cdu_vs_thermal(args, trace, bench, name, groups, unit, directory)
        count += graph_cdu_host(args, trace, bench, name, data, directory)
    return count


# The readings of a CDU drawn against the temperatures of its circuits, the speeds of its pumps
# and its flow rates, named as the other graphs with a second axis: <graph>_vs_Thermal
VS_THERMAL = ("RPM", "L/min")


def graph_cdu_vs_thermal(args, trace: Trace, bench, name: str, groups: dict, unit: str, directory) -> int:
    """The readings of a CDU in a unit, with its temperatures on a second axis, when it has both."""
    if unit not in groups or "Celsius" not in groups:
        return 0
    metadata = bench.get("monitoring")["metadata"]
    graph = Graph(
        args,
        f'CDU {name}: {TITLES.get(unit, unit)} during "{bench.get_bench_name()}" benchmark job'
        f"{context_header(args)}\n{args.title}\n{bench.get_system_title()}",
        "Time [seconds]",
        unit,
        directory,
        f"{quote(TITLES.get(unit, unit), safe=' ')}_vs_Thermal",
        show_source_file=trace,
        legend_title=WINDOW_MEAN_LEGEND,
    )
    graph.set_y2_axis("Temperature (°C)")
    # Share the color cycle across both axes, with dashed lines identifying the temperatures.
    series = [(False, *serie) for serie in groups[unit]] + [(True, *serie) for serie in groups["Celsius"]]
    for index, (is_temperature, label, timestamps, values) in enumerate(series):
        color, marker = curve_style(index)
        axis = graph.get_ax2() if is_temperature else graph.get_ax()
        valid = np.array(values)[np.isfinite(values)]
        legend = statistics_in_label(label, valid) if len(valid) else f"{label} [no readings]"
        axis.plot(
            timestamps,
            values,
            color=color,
            linestyle="--" if is_temperature else "-",
            marker=marker,
            markersize=MARKER_SIZE,
            label=legend,
        )
    graph.prepare_axes(30, 5, points_to_plot=metadata["samples_count"], interval=metadata["iteration_time"])
    graph.get_ax().set_xlim(0, max(1, bench.duration()))
    graph.get_ax().set_xlim(left=zero_margin(graph.get_ax().xaxis, max(1, bench.duration())))
    graph.render()
    return 1


# Optional semantic metric keys shared by CDU profiles, independent of vendor and OIDs.
CIRCUIT_TEMPERATURES = (
    "primary_supply_temperature",
    "primary_return_temperature",
    "secondary_supply_temperature",
    "secondary_return_temperature",
)
# Named as the other graphs with a second axis: <metric of the first axis>_vs_<context of the second>
HOST_COMPARISON = "CDU and host temperatures_vs_PowerConsumption"


def cdu_host_series(monitoring: dict, data: dict, power_metric: str) -> tuple[list[NamedSeries], list[NamedSeries]]:
    """Select circuit/CPU/GPU temperatures and host and GPU power, preserving window positions."""
    count = monitoring["metadata"]["samples_count"]

    def means(metric: dict) -> list[float]:
        values = metric.get("mean", [])[:count]
        # A short series must not shift later windows or fabricate a zero.
        return [np.nan if value is None else value for value in values] + [np.nan] * (count - len(values))

    circuits = [
        (f"CDU / {data['metrics'][key]['name']}", means(data["readings"][key]))
        for key in CIRCUIT_TEMPERATURES
        if key in data["metrics"] and data["metrics"][key]["unit"] == "Celsius"
    ]
    contexts = monitoring["contexts"]
    processors = [
        (f"CPU / {metric.get('name', key)}", means(metric))
        for key, metric in contexts.get("Thermal", {}).get("CPU", {}).items()
        if metric["unit"] == "Celsius" and metric.get("mean")
    ]
    # The accelerators, when the run has some, are cooled by the same circuit as the processors
    accelerators = [
        (f"GPU / {metric.get('name', key)}", means(metric))
        for key, metric in contexts.get("Thermal", {}).get(GPU_FAMILY, {}).items()
        if metric["unit"] == "Celsius" and metric.get("mean")
    ]
    power = contexts.get("PowerConsumption", {})
    watts: list[NamedSeries] = []
    for name in dict.fromkeys(("CPU.package", power_metric)):
        family, key = name.split(".", 1)
        metric = power.get(family, {}).get(key)
        if metric and metric["unit"] == "Watts" and metric.get("mean"):
            watts.append((name, means(metric)))
    for key, metric in power.get(GPU_FAMILY, {}).items():
        if metric["unit"] == "Watts" and metric.get("mean"):
            watts.append((f"{GPU_FAMILY}.{key}", means(metric)))
    return (circuits + processors + accelerators, watts) if circuits and processors else ([], [])


def graph_cdu_host(args, trace: Trace, bench, name: str, data: dict, directory) -> int:
    monitoring = bench.get("monitoring")
    if not any(key in data["metrics"] for key in CIRCUIT_TEMPERATURES):
        return 0
    temperatures, watts = cdu_host_series(monitoring, data, trace.metric_name)
    if not temperatures or not watts:
        return 0
    metadata = monitoring["metadata"]
    times = [index * metadata["iteration_time"] for index in range(metadata["samples_count"])]
    graph = Graph(
        args,
        f'CDU {name} and host temperatures during "{bench.get_bench_name()}" benchmark job'
        f"{context_header(args)}\n{args.title}\n{bench.get_system_title()}",
        "Time [seconds]",
        "Temperature (°C)",
        directory,
        HOST_COMPARISON,
        show_source_file=trace,
        legend_title=WINDOW_MEAN_LEGEND,
    )
    graph.set_y2_axis("Power (Watts)")
    # Share the color cycle across both axes, with dashed lines identifying power: beyond its 10
    # colors, as with the GPUs, the curves change of marker, see curve_style()
    for index, (label, values) in enumerate(temperatures + watts):
        color, marker = curve_style(index)
        is_power = index >= len(temperatures)
        axis = graph.get_ax2() if is_power else graph.get_ax()
        valid = np.array(values)[np.isfinite(values)]
        legend = statistics_in_label(label, valid) if len(valid) else f"{label} [no readings]"
        axis.plot(
            times,
            values,
            color=color,
            linestyle="--" if is_power else "-",
            marker=marker,
            markersize=MARKER_SIZE,
            label=legend,
        )
    graph.prepare_axes(30, 5, points_to_plot=metadata["samples_count"], interval=metadata["iteration_time"])
    graph.get_ax().set_xlim(0, max(1, bench.duration()))
    graph.get_ax().set_xlim(left=zero_margin(graph.get_ax().xaxis, max(1, bench.duration())))
    graph.render()
    return 1
