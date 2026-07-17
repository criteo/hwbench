from __future__ import annotations

from typing import Any  # noqa: F401

import matplotlib.pyplot as plt
import numpy as np

from graph.graph import GRAPH_TYPES, Graph
from graph.scaling import _scaling_perf_value
from hwbench.bench.monitoring_structs import MonitoringContextKeys


def max_versus_graph(args, output_dir, job: str, traces_name: list) -> int:
    """Plot bar graph to compare traces during individual benchmarks."""
    if args.verbose:
        print(f"Max versus: rendering {job}")
    max_bars_for_horizontal_label = 10
    rendered_graphs = 0
    temp_outdir = output_dir.joinpath("max_versus")

    benches = args.traces[0].get_benches_by_job_per_emp(job)
    # For all subjobs sharing the same engine module parameter
    # i.e int128
    for emp in benches:
        aggregated_perfs = {}  # type: dict[str, dict[str, Any]]
        aggregated_perfs_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_watt = {}  # type: dict[str, dict[str, Any]]
        aggregated_cpu_clock = {}  # type: dict[str, dict[str, Any]]
        max_perf = {}  # type: dict[str, list]
        max_perfs_watt = {}  # type: dict[str, list]
        max_watt = {}  # type: dict[str, list]
        max_cpu_clock = {}  # type: dict[str, list]
        max_workers = {}  # type: dict[str, list]
        perf_list, unit = benches[emp]["metrics"]
        # For each metric we need to plot
        for perf in perf_list:
            if perf not in aggregated_perfs:
                aggregated_perfs[perf] = {}
                aggregated_perfs_watt[perf] = {}
                aggregated_watt[perf] = {}
                aggregated_cpu_clock[perf] = {}
                max_perf[perf] = [0] * len(traces_name)
                max_perfs_watt[perf] = [0] * len(traces_name)
                max_watt[perf] = [0] * len(traces_name)
                max_cpu_clock[perf] = [0] * len(traces_name)
                max_workers[perf] = [0] * len(traces_name)
            # We want a datastructure where metrics of each iteration on the number of workers reports performance for each trace
            # It looks like :
            #  {2: [1264.58, 1063.5, 999.14, 1174.89],
            #   4: [2496.75, 2125.14, 1998.55, 2311.87],
            #   6: [3717.81, 3197.44, 2996.02, 3450.07],
            #   8: [4939.88, 4265.68, 4031.51, 4579.23],
            #  16: [9627.07, 8482.82, 7987.64, 8955.85],
            #  32: [17591.86, 17058.58, 15966.49, 17183.78],
            #  64: [0, 32507.33, 32468.21, 31999.65],
            #  96: [0, 0, 47910.2, 0]}
            # In this example 64 & 96 workers have partial values because some hosts didn't had enough cores to do it

            # For every trace file given at the command line
            index = 0
            for trace in args.traces:
                # Let's iterate on each Bench from this trace file matching this em
                for bench in trace.get_benches_by_job_per_emp(job)[emp]["bench"]:
                    if bench.workers() not in aggregated_perfs[perf]:
                        # If the worker count is not known yet, let's init all structures with as much zeros as the number of traces
                        # This will be the default value in case of the host doesn't have performance results
                        aggregated_perfs[perf][bench.workers()] = [0] * len(traces_name)
                        aggregated_perfs_watt[perf][bench.workers()] = [0] * len(traces_name)
                        aggregated_watt[perf][bench.workers()] = [0] * len(traces_name)
                        aggregated_cpu_clock[perf][bench.workers()] = [0] * len(traces_name)
                    bench.add_perf(
                        perf,
                        aggregated_perfs[perf][bench.workers()],
                        aggregated_perfs_watt[perf][bench.workers()],
                        aggregated_watt[perf][bench.workers()],
                        cpu_clock=aggregated_cpu_clock[perf][bench.workers()],
                        # Average the clock only over the cores pinned during the
                        # benchmark (falls back to all cores when there is no pin).
                        cpu_clock_cores=bench.pinned_core_names(),
                        index=index,
                    )

                    if bench.skipped():
                        max_workers[perf][index] = -1
                    temp_max_perf = aggregated_perfs[perf][bench.workers()][index]
                    if temp_max_perf > max_perf[perf][index]:
                        max_perf[perf][index] = temp_max_perf
                        max_perfs_watt[perf][index] = aggregated_perfs_watt[perf][bench.workers()][index]
                        max_watt[perf][index] = aggregated_watt[perf][bench.workers()][index]
                        max_cpu_clock[perf][index] = aggregated_cpu_clock[perf][bench.workers()][index]
                        max_workers[perf][index] = bench.workers()

                index = index + 1

        for graph_type in GRAPH_TYPES:
            # Let's render each performance graph
            graph_type_title = ""

            # for each performance metric we have to plot
            for perf in perf_list:
                clean_perf = perf.replace(" ", "").replace("/", "")
                y_label = unit
                outdir = temp_outdir.joinpath(graph_type)
                outfile = f"{bench.get_title_engine_name().replace(' ', '_')}"

                # Let's define the tree architecture based on the benchmark profile
                # If the benchmark has multiple performance results, let's put them in a specific directory
                outdir = outdir.joinpath(emp, perf) if len(perf_list) > 1 else outdir.joinpath(emp)

                # Select the proper datasource and titles/labels regarding the graph type
                if graph_type == "perf_watt":
                    graph_type_title = f"Max versus '{graph_type}': '{bench.get_title_engine_name()} / {args.traces[0].get_metric_name()}'"
                    graph_type_title += ": Bigger is better"
                    y_label = f"{unit} per Watt"
                    y_max = max_perfs_watt
                elif graph_type == "watts":
                    graph_type_title = f"Max versus '{graph_type}': {args.traces[0].get_metric_name()}"
                    graph_type_title += ": Lower is better"
                    y_label = "Watts"
                    y_max = max_watt
                elif graph_type == "cpu_clock":
                    # Clock of the pinned cores reached when the product hit its maximum performance.
                    graph_type_title = f"Max versus '{graph_type}' on pinned cores: {bench.get_title_engine_name()}"
                    y_label = "Mhz"
                    y_max = max_cpu_clock
                else:
                    graph_type_title = f"Max versus '{graph_type}': {bench.get_title_engine_name()}"
                    graph_type_title += ": Bigger is better"
                    y_max = max_perf

                # Prepare the plot for this benchmark
                bar_colors = ["tab:red", "tab:blue", "tab:green", "tab:orange"]
                # Now render the max performance graph
                # Concept is to show what every product reached as a maximum perf and plot them together
                # This way we have on a single graph showing the max of 32 cores vs a 48 cores vs a 64 cores.
                # A per-core breakdown is meaningless for the CPU clock (it is
                # already an average across cores), so only emit the total there.
                max_perf_types = ["max_perf_total"]
                if graph_type != "cpu_clock":
                    max_perf_types.append("max_perf_per_core")
                for max_perf_type in max_perf_types:
                    title = f'{args.title}\n\n{graph_type_title} during "{job}" benchmark\n'
                    if max_perf_type == "max_perf_per_core":
                        title += f"\nPer core maximum performance during {bench.duration()} seconds"
                        y_max_per_core = [0] * len(y_max[perf])
                        # Let's compute the performance per physical core
                        for ymax_nb in range(len(y_max[perf])):
                            y_max_per_core[ymax_nb] = y_max[perf][ymax_nb] / args.traces[ymax_nb].get_physical_cores()
                        y_serie = np.array(y_max_per_core)
                    elif graph_type == "cpu_clock":
                        title += f"\nClock reached at maximum performance during {bench.duration()} seconds"
                        y_serie = np.array(y_max[perf])
                    else:
                        title += f"\nProduct maximum performance during {bench.duration()} seconds"
                        y_serie = np.array(y_max[perf])

                    graph = Graph(
                        args,
                        title,
                        "",
                        y_label,
                        outdir,
                        f"{max_perf_type}_{outfile}{graph_type}_{clean_perf}",
                    )

                    # zorder=3 ensure the graph with be on top of the grid
                    graph.get_ax().bar(traces_name, y_serie, color=bar_colors, zorder=3)

                    # Let's put the normalized value in the center of the bar
                    for trace_name in range(len(traces_name)):
                        if y_serie[trace_name] > 0:
                            graph.get_ax().text(
                                trace_name,
                                y_serie[trace_name] // 2,
                                graph.human_format(y_serie[trace_name]),
                                ha="center",
                                color="white",
                                fontsize=16,
                                rotation="vertical"
                                if len(traces_name) > max_bars_for_horizontal_label
                                else "horizontal",
                            )

                    # Add the number of workers, needed to reach that perf, below the trace name
                    bar_labels = traces_name.copy()
                    for trace_nb in range(len(traces_name)):
                        if max_workers[perf][trace_nb] < 0:
                            bar_labels[trace_nb] += "\nbenchmark skipped"
                        else:
                            bar_labels[trace_nb] += f"\n{max_workers[perf][trace_nb]} workers"
                    graph.get_ax().axes.xaxis.set_ticks(traces_name)
                    graph.get_ax().set_xticklabels(bar_labels)

                    graph.prepare_axes(legend=False)
                    graph.render()
                    rendered_graphs += 1

    return rendered_graphs


def _bench_power(bench, metric_name: str) -> float | None:
    """Mean power (Watts) of a bench for the trace's selected power metric.

    metric_name is the "component.measure" power metric chosen on the command line
    (e.g. CPU.package, BMC.ServerInChassis). None when not collected.
    """
    try:
        metric = bench.get_monitoring_metric_by_name(MonitoringContextKeys.PowerConsumption, metric_name)
    except (KeyError, ValueError):
        return None
    means = metric.get_mean()
    return float(np.mean(means)) if len(means) else None


def _bench_avg_core_clock(bench) -> float | None:
    """Mean core frequency (MHz) averaged over all cores of a bench, or None."""
    cores = bench.get_all_metrics(MonitoringContextKeys.Freq, "Core")
    if not cores:
        return None
    per_core = [float(np.mean(c.get_mean())) for c in cores if len(c.get_mean())]
    return float(np.mean(per_core)) if per_core else None


def _bench_avg_ipc(bench) -> float | None:
    """Mean IPC (instructions per cycle) averaged over all cores of a bench, or None."""
    cores = bench.get_all_metrics(MonitoringContextKeys.IPC, "Core")
    if not cores:
        return None
    per_core = [float(np.mean(c.get_mean())) for c in cores if len(c.get_mean())]
    return float(np.mean(per_core)) if per_core else None


def _bench_perf_cov(bench) -> float | None:
    """Per-worker performance spread of a bench (coefficient of variation, %).

    Computed from the per-instance "bogo op/s" distribution stress-ng records in
    the bench "detail" (extracted from its YAML output); lower means the workers
    performed more homogeneously. None when no per-worker detail is available.
    """
    detail = bench.get("detail")
    if not isinstance(detail, dict):
        return None
    values = detail.get("bogo op/s")
    if not isinstance(values, list) or len(values) < 2:
        return None
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if mean == 0:
        return None
    return float(arr.std() / mean * 100.0)


def _trace_job_step_metrics(trace, job: str) -> dict:
    """Per engine-module-parameter, per scaling-step metrics for one trace's job.

    For each emp (e.g. float128) return {worker count: metrics} covering every
    scaling step, where metrics holds: performance, CPU package power, average
    core clock, IPC, worker count, the per-worker performance spread (CoV%) and
    the scaling linearity efficiency at that step (step performance vs the ideal
    linear projection anchored on the first step -- so the first step reads 100%).
    """
    metric_name = trace.get_metric_name()
    out = {}  # type: dict
    for emp, info in trace.get_benches_by_job_per_emp(job).items():
        benches = sorted((b for b in info["bench"] if not b.skipped()), key=lambda b: b.workers())
        if not benches:
            continue
        perf_key = info["metrics"][0][0]
        unit = info["metrics"][1]
        workers = [b.workers() for b in benches]
        perf = [_scaling_perf_value(b, perf_key) for b in benches]
        # First-step slope for the linear projection; None when the first step has
        # no throughput (an anchor of 0 would make every linearity undefined).
        slope = (perf[0] / workers[0]) if (workers[0] > 0 and perf[0] > 0) else None
        per_step = {}  # type: dict
        for i, bench in enumerate(benches):
            lin_full = perf[i] / (slope * workers[i]) * 100 if slope else None
            per_step[bench.workers()] = {
                "engine_module": bench.engine_module(),
                "unit": unit,
                "workers": workers[i],
                "perf": perf[i],
                "power": _bench_power(bench, metric_name),
                "clock": _bench_avg_core_clock(bench),
                "ipc": _bench_avg_ipc(bench),
                "cov": _bench_perf_cov(bench),
                "lin_full": lin_full,
            }
        out[emp] = per_step
    return out


def _trace_job_metrics(trace, job: str) -> dict:
    """Per engine-module-parameter full-load metrics for one trace's job.

    The full-load (max workers) step of _trace_job_step_metrics, kept as the
    reference point for the single-report comparison and the scorecard.
    """
    out = {}  # type: dict
    for emp, per_step in _trace_job_step_metrics(trace, job).items():
        if per_step:
            out[emp] = per_step[max(per_step)]
    return out


def _hf(n: float) -> str:
    """Human-readable number with a K/M/G suffix (mirrors Graph.human_format)."""
    for unit, div in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.2f}{unit}"
    return f"{n:.1f}"


def _ratio(value, ref) -> str:
    """Ratio string 'x.xxx' against the reference, or '-' when not computable."""
    if value is None or ref in (None, 0):
        return "-"
    return f"{value / ref:.2f}x"


def _geomean(values) -> float | None:
    vals = [v for v in values if v and v > 0]
    return float(np.exp(np.mean(np.log(vals)))) if vals else None


def _render_traces_comparison(
    args,
    traces,
    metrics,
    cores,
    sweep,
    *,
    scope_title: str,
    columns_scope: str,
    aggregate_scope: str,
    ref_missing_reason: str,
) -> str:
    """Build the traces-comparison report text shared by the full-load and the
    per-step reports.

    metrics maps {trace name: {(job, emp): metrics}} already reduced to the scope
    being reported (full load, or one scaling step); a benchmark absent from a
    trace's mapping is rendered as N/A. cores/sweep are per-trace. The scope_*
    strings tailor the wording (heading suffix, the "Columns" note and the
    aggregate header) and ref_missing_reason explains, in a per-section note, why
    a benchmark the reference lacks is excluded from the aggregate. Returns the
    whole report as text.
    """
    ref_name = traces[0].get_name()
    # Benchmark keys: those of the reference first (in job order), then any extra
    # benchmark other traces have but the reference does not (e.g. AVX-512 on a CPU
    # that lacks it). The latter are reported as N/A and excluded from the aggregate.
    ordered = list(metrics[ref_name].keys())
    for tm in metrics.values():
        for key in tm:
            if key not in ordered:
                ordered.append(key)

    # IPC columns are only shown when at least one trace collected IPC.
    has_ipc = any(m.get("ipc") is not None for tm in metrics.values() for m in tm.values())

    headers = [
        "Trace",
        "Wrk",
        "Perf",
        "Δperf",
        "Perf/core",
        "Δperf/core",
        "Power",
        "Δpower",
        "Perf/W",
        "Clock",
        "Δclock",
    ]
    if has_ipc:
        headers += ["IPC", "ΔIPC"]
    headers += ["CoV", "Linearity"]
    left = {"Trace"}

    def _bench_row(tname, i, m, ref_m):
        """One table row. ref_m is None when the reference has no value for this
        benchmark in this scope -- then every ratio is reported as N/A."""
        ct, cr = cores[tname], cores[ref_name]
        pc = m["perf"] / ct if ct else None

        def R(value, ref_value):
            return "N/A" if ref_m is None else _ratio(value, ref_value)

        ref_pc = ref_m["perf"] / cr if (ref_m and cr) else None
        ref_ppw = ref_m["perf"] / ref_m["power"] if (ref_m and ref_m["power"]) else None
        return {
            "Trace": tname + ("*" if i == 0 else ""),
            "Wrk": str(m["workers"]),
            "Perf": _hf(m["perf"]),
            "Δperf": R(m["perf"], ref_m["perf"] if ref_m else None),
            "Perf/core": _hf(pc) if pc is not None else "-",
            "Δperf/core": R(pc, ref_pc),
            "Power": f"{m['power']:.0f}W" if m["power"] is not None else "n/a",
            "Δpower": R(m["power"], ref_m["power"] if ref_m else None),
            "Perf/W": R(m["perf"] / m["power"] if m["power"] else None, ref_ppw),
            "Clock": f"{m['clock']:.0f}M" if m["clock"] is not None else "n/a",
            "Δclock": R(m["clock"], ref_m["clock"] if ref_m else None),
            "IPC": f"{m['ipc']:.2f}" if m["ipc"] is not None else "n/a",
            "ΔIPC": R(m["ipc"], ref_m["ipc"] if ref_m else None),
            "CoV": f"{m['cov']:.1f}%" if m["cov"] is not None else "-",
            # Deviation from perfect linear scaling (like the linearity graphs):
            # 0% = perfect, negative = scaling loss.
            "Linearity": f"{m['lin_full'] - 100:+.0f}%" if m["lin_full"] is not None else "-",
        }

    # Build every row first so column widths are shared across all blocks.
    blocks = []  # type: list
    for key in ordered:
        ref_m = metrics[ref_name].get(key)  # None when the reference has no value here
        # Engine/unit come from the reference, or any trace that has the benchmark.
        sample = ref_m or next(m for tm in metrics.values() if (m := tm.get(key)))
        rows = []
        for i, trace in enumerate(traces):
            tname = trace.get_name()
            m = metrics[tname].get(key)
            if m is None:
                # Trace has no value for this benchmark in this scope.
                rows.append({h: ("N/A" if h != "Trace" else tname + ("*" if i == 0 else "")) for h in headers})
                continue
            rows.append(_bench_row(tname, i, m, ref_m))
        note = None if ref_m else f"reference {ref_name} {ref_missing_reason}; excluded from the aggregate"
        blocks.append((f"{sample['engine_module']}/{key[1]}", sample["unit"], rows, note))

    widths = {h: len(h) for h in headers}
    for _, _, rows, _ in blocks:
        for row in rows:
            for h in headers:
                widths[h] = max(widths[h], len(row[h]))

    def _cell(h, v):
        return str(v).ljust(widths[h]) if h in left else str(v).rjust(widths[h])

    def _line(cells):
        return "  ".join(_cell(h, cells[h]) for h in headers)

    sep = "  ".join("-" * widths[h] for h in headers)

    lines = [f"Traces comparison (scaling){scope_title}", args.title, "", f"Reference : {ref_name}", ""]
    for i, trace in enumerate(traces):
        cpu = trace.get_cpu()
        tname = trace.get_name()
        smin, smax = sweep[tname]
        tag = "(ref) " if i == 0 else "      "
        lines.append(
            f"  {tag}{tname:<22} {cpu.get('sockets', 1)}x {cpu['model']} - "
            f"{cores[tname]:>3} cores / {cpu['numa_domains']:>2} NUMA   scaling {smin}->{smax} workers"
        )
    # Name the selected power metric; note it if it varies across traces.
    power_metrics = sorted({trace.get_metric_name() for trace in traces})
    power_label = power_metrics[0] if len(power_metrics) == 1 else "the per-trace selected power metric"

    lines.append("")
    lines.append(f"Columns ({columns_scope}):")
    lines.append("  Trace     = trace logical name; '*' marks the reference (first trace).")
    lines.append("  Wrk       = worker count for this section.")
    lines.append("  Perf      = benchmark performance (unit shown per section); Δperf = ratio to the reference.")
    lines.append("  Perf/core = performance per physical CPU core (physical cores, not SMT threads or workers);")
    lines.append("              Δperf/core = ratio to the reference.")
    lines.append(f"  Power     = mean {power_label} power in Watts; Δpower = ratio to the reference.")
    lines.append("  Perf/W    = performance per watt, as a ratio to the reference (Δperf / Δpower).")
    lines.append("  Clock     = mean CPU core frequency in MHz; Δclock = ratio to the reference.")
    if has_ipc:
        lines.append("  IPC       = mean instructions per cycle across cores; ΔIPC = ratio to the reference.")
    lines.append("  CoV       = Coefficient of Variation (std-dev / mean, %) of the per-worker performance:")
    lines.append("              how evenly the workers performed (lower = more homogeneous, 0% = identical);")
    lines.append("              from the stress-ng per-worker detail, '-' when absent.")
    lines.append("  Linearity = deviation from perfect linear scaling, as in the scaling graphs:")
    lines.append("              (perf / ideal linear projection from the first step) - 100%.")
    lines.append("              0% = perfectly linear, negative = scaling loss, positive = superlinear.")
    lines.append("")

    for title, unit, rows, note in blocks:
        lines.append(f"### {title}  [{unit}]")
        if note:
            lines.append(f"(note: {note})")
        lines.append(_line({h: h for h in headers}))
        lines.append(sep)
        lines += [_line(row) for row in rows]
        lines.append("")

    # Aggregate: geometric mean of the ratios across every benchmark in scope,
    # plus the mean per-worker homogeneity.
    # Same column order as the per-benchmark tables (minus the absolute values,
    # which don't aggregate): Δperf, Δperf/core, Δpower, Perf/W, Δclock, ΔIPC, CoV, Linearity.
    agg_headers = ["Trace", "Δperf", "Δperf/core", "Δpower", "Perf/W", "Δclock"]
    if has_ipc:
        agg_headers += ["ΔIPC"]
    agg_headers += ["CoV", "Linearity"]
    agg_widths = {h: len(h) for h in agg_headers}
    agg_rows = []

    def _fmt_ratio(g):
        return f"{g:.2f}x" if g else "-"

    for i, trace in enumerate(traces):
        tname = trace.get_name()
        pr, pcr, wr, cr, ipcr, lins, covs = [], [], [], [], [], [], []
        for key in ordered:
            m = metrics[tname].get(key)
            ref_m = metrics[ref_name].get(key)
            # Skip benchmarks the reference has no value for (reported as N/A above
            # and excluded from the aggregate).
            if not m or not ref_m:
                continue
            if ref_m["perf"]:
                pr.append(m["perf"] / ref_m["perf"])
            if cores[tname] and cores[ref_name] and ref_m["perf"]:
                pcr.append((m["perf"] / cores[tname]) / (ref_m["perf"] / cores[ref_name]))
            if m["power"] and ref_m["power"]:
                wr.append(m["power"] / ref_m["power"])
            if m["clock"] and ref_m["clock"]:
                cr.append(m["clock"] / ref_m["clock"])
            if m["ipc"] and ref_m["ipc"]:
                ipcr.append(m["ipc"] / ref_m["ipc"])
            if m["lin_full"] is not None:
                lins.append(m["lin_full"])
            if m["cov"] is not None:
                covs.append(m["cov"])
        gperf, gpow = _geomean(pr), _geomean(wr)
        row = {
            "Trace": tname + ("*" if i == 0 else ""),
            "Δperf": _fmt_ratio(gperf),
            "Δperf/core": _fmt_ratio(_geomean(pcr)),
            "Δpower": _fmt_ratio(gpow),
            "Δclock": _fmt_ratio(_geomean(cr)),
            "Perf/W": f"{gperf / gpow:.2f}x" if gperf and gpow else "-",
            "Linearity": f"{np.mean(lins) - 100:+.0f}%" if lins else "-",
            "CoV": f"{np.mean(covs):.1f}%" if covs else "-",
        }
        if has_ipc:
            row["ΔIPC"] = _fmt_ratio(_geomean(ipcr))
        agg_rows.append(row)
    for row in agg_rows:
        for h in agg_headers:
            agg_widths[h] = max(agg_widths[h], len(row[h]))

    def _agg_cell(h, v):
        return str(v).ljust(agg_widths[h]) if h == "Trace" else str(v).rjust(agg_widths[h])

    def _agg_line(cells):
        return "  ".join(_agg_cell(h, cells[h]) for h in agg_headers)

    lines.append(f"### Aggregate (geometric mean of {aggregate_scope} across all benchmarks)")
    lines.append(_agg_line({h: h for h in agg_headers}))
    lines.append("  ".join("-" * agg_widths[h] for h in agg_headers))
    lines += [_agg_line(row) for row in agg_rows]

    return "\n".join(line.rstrip() for line in lines) + "\n"


def _comparison_jobs(ref) -> list:
    """Benchmark job names in the reference's order (job, then emp encounter order)."""
    jobs = []  # type: list[str]
    for name in sorted(ref.bench_list()):
        job = ref.bench(name).job_name()
        if job not in jobs:
            jobs.append(job)
    return jobs


def _trace_cores_and_sweep(trace) -> tuple:
    """(physical core count, (min workers, max workers)) for one trace."""
    allw = [trace.bench(n).workers() for n in trace.bench_list()]
    return trace.get_cpu()["physical_cores"], ((min(allw), max(allw)) if allw else (0, 0))


def write_scaling_comparison(args, output_dir) -> int:
    """Write max_versus/benchmarks_summary.txt comparing every trace to the first one.

    In scaling mode the first trace on the command line is the reference. For each
    benchmark type (engine module / variant) the report lists, at the full-load
    (max workers) step: total performance and its ratio to the reference,
    performance per physical core and its ratio, CPU package power and clock with
    their ratios, and -- when the per-worker detail is available -- the
    performance homogeneity (CoV%, lower is more uniform). Each trace also carries
    its scaling linearity efficiency (full-load performance vs the ideal linear
    projection from the first step). A closing aggregate section gives the
    geometric mean of the ratios across all benchmarks. Returns 1 when written.
    """
    traces = args.traces
    if not traces:
        return 0
    jobs = _comparison_jobs(traces[0])

    # Per trace: {(job, emp): full-load metrics}, physical-core count and sweep.
    metrics = {}  # type: dict
    cores = {}  # type: dict
    sweep = {}  # type: dict
    for trace in traces:
        tm = {}  # type: dict
        for job in jobs:
            for emp, m in _trace_job_metrics(trace, job).items():
                tm[(job, emp)] = m
        metrics[trace.get_name()] = tm
        cores[trace.get_name()], sweep[trace.get_name()] = _trace_cores_and_sweep(trace)

    text = _render_traces_comparison(
        args,
        traces,
        metrics,
        cores,
        sweep,
        scope_title="",
        columns_scope="all values taken at full load = the max workers each trace scaled to",
        aggregate_scope="full-load ratios",
        ref_missing_reason="did not run this benchmark",
    )
    versus_dir = output_dir.joinpath("max_versus")
    versus_dir.mkdir(parents=True, exist_ok=True)
    summary_file = versus_dir.joinpath("benchmarks_summary.txt")
    summary_file.write_text(text)
    print(f"Performance scaling: wrote traces comparison to {summary_file}")
    return 1


def write_scaling_step_comparisons(args, output_dir) -> int:
    """Write one traces comparison per scaling step under scaling/.

    Same format and columns as max_versus/benchmarks_summary.txt, but instead of a
    single report at full load, one file per scaling step (worker count) --
    scaling/summary/benchmarks_summary_<N>_workers.txt -- each comparing every
    trace to the first (reference) using the values measured at that step. A trace
    with no run at a given worker count is reported as N/A in that step's file.
    Returns the number of files written (0 with fewer than two traces).
    """
    traces = args.traces
    if len(traces) < 2:
        return 0
    jobs = _comparison_jobs(traces[0])

    # Per trace: {(job, emp): {workers: metrics}}, physical-core count and sweep,
    # plus the union of every worker count seen across traces/benchmarks.
    step_metrics = {}  # type: dict
    cores = {}  # type: dict
    sweep = {}  # type: dict
    all_steps = set()  # type: set
    for trace in traces:
        tm = {}  # type: dict
        for job in jobs:
            for emp, per_step in _trace_job_step_metrics(trace, job).items():
                tm[(job, emp)] = per_step
                all_steps.update(per_step)
        step_metrics[trace.get_name()] = tm
        cores[trace.get_name()], sweep[trace.get_name()] = _trace_cores_and_sweep(trace)

    if not all_steps:
        return 0

    summary_dir = output_dir.joinpath("scaling", "summary")
    summary_dir.mkdir(parents=True, exist_ok=True)
    steps = sorted(all_steps)
    # Zero-pad the worker count in the filename so the files list in sweep order.
    width = len(str(steps[-1]))
    written = 0
    for n in steps:
        # This step's metrics: {trace name: {(job, emp): metrics}}, keeping only the
        # benchmarks each trace actually ran at n workers.
        metrics = {
            tname: {key: per_step[n] for key, per_step in tm.items() if n in per_step}
            for tname, tm in step_metrics.items()
        }
        text = _render_traces_comparison(
            args,
            traces,
            metrics,
            cores,
            sweep,
            scope_title=f" - {n} workers",
            columns_scope=f"all values taken at this scaling step = {n} workers",
            aggregate_scope=f"ratios at {n} workers",
            ref_missing_reason=f"has no result at {n} workers",
        )
        summary_file = summary_dir.joinpath(f"benchmarks_summary_{n:0{width}d}_workers.txt")
        summary_file.write_text(text)
        written += 1
    print(f"Performance scaling: wrote {written} per-step traces comparison(s) to {summary_dir}")
    return written


def _aggregate_metrics(traces) -> tuple[list, str, dict]:
    """Per-trace aggregate metrics vs the first trace (the reference).

    Returns (ordered trace names, reference name, {name: metrics}) where metrics
    holds the geometric-mean ratios to the reference across all comparable
    benchmarks (dperf, dcore, dpow, dipc, dclk, ppw) plus the mean full-load
    linearity (lin, deviation %) and per-worker homogeneity (cov, %). Mirrors the
    aggregate section of write_scaling_comparison.
    """
    ref = traces[0]
    ref_name = ref.get_name()
    jobs = []  # type: list[str]
    for name in sorted(ref.bench_list()):
        job = ref.bench(name).job_name()
        if job not in jobs:
            jobs.append(job)

    metrics = {}  # type: dict
    cores = {}  # type: dict
    for trace in traces:
        tm = {}  # type: dict
        for job in jobs:
            for emp, m in _trace_job_metrics(trace, job).items():
                tm[(job, emp)] = m
        metrics[trace.get_name()] = tm
        cores[trace.get_name()] = trace.get_physical_cores()

    out = {}  # type: dict
    for trace in traces:
        n = trace.get_name()
        pr, pcr, wr, ipc, clk, lins, covs = [], [], [], [], [], [], []
        for key, m in metrics[n].items():
            rm = metrics[ref_name].get(key)
            if not m or not rm:
                continue
            if rm["perf"]:
                pr.append(m["perf"] / rm["perf"])
            if cores[n] and cores[ref_name] and rm["perf"]:
                pcr.append((m["perf"] / cores[n]) / (rm["perf"] / cores[ref_name]))
            if m["power"] and rm["power"]:
                wr.append(m["power"] / rm["power"])
            if m["ipc"] and rm["ipc"]:
                ipc.append(m["ipc"] / rm["ipc"])
            if m["clock"] and rm["clock"]:
                clk.append(m["clock"] / rm["clock"])
            if m["lin_full"] is not None:
                lins.append(m["lin_full"])
            if m["cov"] is not None:
                covs.append(m["cov"])
        gperf, gpow = _geomean(pr), _geomean(wr)
        out[n] = {
            "dperf": gperf,
            "dcore": _geomean(pcr),
            "dpow": gpow,
            "dipc": _geomean(ipc),
            "dclk": _geomean(clk),
            "ppw": (gperf / gpow) if gperf and gpow else None,
            # Deviation from perfect linear scaling (0% = linear), like the text
            # report: lin_full is the ratio-percent, so subtract 100.
            "lin": float(np.mean(lins)) - 100 if lins else None,
            "cov": float(np.mean(covs)) if covs else None,
        }
    return [trace.get_name() for trace in traces], ref_name, out


def _traces_caption(traces) -> str:
    """Full per-trace system description block, rendered below the exec graphs.

    System / Bios / Kernel / Processor each on their own line.
    """
    parts = []
    for i, trace in enumerate(traces):
        tag = trace.get_name() + (" (ref)" if i == 0 else "")
        dmi = trace.get_dmi()
        cpu = trace.get_cpu()
        kernel = trace.get_kernel()
        parts.append(
            f"{tag}:\n"
            f"  System   : {dmi['serial']} {dmi['product']}\n"
            f"  Bios     : v{dmi['bios']['version']}\n"
            f"  Kernel   : {kernel['release']}\n"
            f"  Processor: {cpu.get('sockets', 1)}x {cpu['model']}\n"
            f"             {cpu['physical_cores']} physical cores, {cpu['numa_domains']} NUMA domains"
        )
    return "\n\n".join(parts)


# Column meanings, rendered below the scorecard next to the system description.
_METRICS_CAPTION = (
    "Metrics (geometric mean across benchmarks, at full load, vs reference):\n"
    "  Δperf     : total throughput ratio\n"
    "  Δperf/core    : throughput per physical core ratio\n"
    "  ΔIPC      : instructions-per-cycle ratio\n"
    "  Perf/W    : performance-per-watt ratio (Δperf / Δpower)\n"
    "  Δpower      : CPU package power ratio (lower is better)\n"
    "  Δclock      : mean core-frequency ratio\n"
    "  Linearity : deviation from perfect linear scaling (0% = linear)\n"
    "  CoV       : per-worker performance spread (lower = more homogeneous)\n"
    "\n"
    "Color: green = better than the reference, red = worse, neutral = same."
)


def render_versus_scorecard(args, output_dir) -> int:
    """Render an executive-summary scorecard heatmap of the aggregate.

    One row per trace, one column per aggregate metric, each cell annotated with
    the real value and colored vs the reference (green = better than the
    reference, red = worse, ~neutral = same). Direction is folded per metric so
    green always means "better": power and CoV are inverted (lower is greener),
    and linearity uses its signed deviation. Written to
    max_versus/performance_summary_scorecard.
    """
    traces = args.traces
    if len(traces) < 2:
        return 0
    names, ref_name, agg = _aggregate_metrics(traces)
    ref = agg[ref_name]

    def rx(v):
        return f"{v:.2f}x" if v is not None else "n/a"

    def pc(v):
        return f"{v:+.0f}%" if v is not None else "n/a"

    def cx(v):
        return f"{v:.1f}%" if v is not None else "n/a"

    # (label, value key, display fn, goodness-vs-reference fn -> signed float or
    # None). Positive goodness = better than the reference. None fn = neutral.
    cols = [
        ("Δperf", "dperf", rx, lambda a: float(np.log2(a["dperf"])) if a["dperf"] else None),
        ("Δperf/core", "dcore", rx, lambda a: float(np.log2(a["dcore"])) if a["dcore"] else None),
        ("ΔIPC", "dipc", rx, lambda a: float(np.log2(a["dipc"])) if a["dipc"] else None),
        ("Perf/W", "ppw", rx, lambda a: float(np.log2(a["ppw"])) if a["ppw"] else None),
        ("Δpower", "dpow", rx, lambda a: -float(np.log2(a["dpow"])) if a["dpow"] else None),
        ("Δclock", "dclk", rx, lambda a: float(np.log2(a["dclk"])) if a["dclk"] else None),
        (
            "Linearity",
            "lin",
            pc,
            lambda a: (a["lin"] - ref["lin"]) if (a["lin"] is not None and ref["lin"] is not None) else None,
        ),
        (
            "CoV",
            "cov",
            cx,
            lambda a: (ref["cov"] - a["cov"]) if (a["cov"] is not None and ref["cov"] is not None) else None,
        ),
    ]

    # Per column: normalize the signed goodness to [-1, 1] (0 = reference) so a
    # single diverging colormap works across metrics with different units.
    grid = np.full((len(names), len(cols)), np.nan)
    for j, (_, _, _, gfn) in enumerate(cols):
        if gfn is None:
            continue
        vals = np.array([gfn(agg[n]) if gfn(agg[n]) is not None else np.nan for n in names])
        scale = np.nanmax(np.abs(vals)) if np.any(np.isfinite(vals)) else 0.0
        if scale > 0:
            grid[:, j] = vals / scale

    fig, ax = plt.subplots(figsize=(1.15 * len(cols) + 2.5, 0.62 * len(names) + 1.8))
    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("0.9")  # neutral / missing cells
    ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([c for c, _, _, _ in cols])
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels([n + (" *" if n == ref_name else "") for n in names])
    for i, n in enumerate(names):
        for j, (_, key, dfn, _) in enumerate(cols):
            ax.text(j, i, dfn(agg[n][key]), ha="center", va="center", fontsize=9)

    title = f"{args.title}\n\nPerformance executive summary (vs {ref_name})\n"
    title += "green = better than reference, red = worse, neutral = same; * = reference"
    ax.set_title(title, fontsize=10)
    # Two side-by-side blocks below the graph: system descriptions on the left
    # half, the meaning of each metric column on the right half.
    sys_caption = ax.text(
        0.0,
        -0.18,
        _traces_caption(traces),
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=7,
        family="monospace",
    )
    metrics_caption = ax.text(
        0.5,
        -0.18,
        _METRICS_CAPTION,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=7,
        family="monospace",
    )

    outdir = output_dir.joinpath("max_versus")
    outdir.mkdir(parents=True, exist_ok=True)
    summary_file = outdir.joinpath(f"performance_summary_scorecard.{args.format}")
    fig.savefig(
        str(summary_file),
        format=args.format,
        dpi=args.dpi,
        bbox_inches="tight",
        pad_inches=0.3,
        bbox_extra_artists=[sys_caption, metrics_caption],
    )
    fig.clear()
    plt.close(fig)
    print(f"Max versus: wrote executive summary scorecard to {summary_file}")
    return 1
