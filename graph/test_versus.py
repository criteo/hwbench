from types import SimpleNamespace

import pytest

from graph.graph import MAX_LEGEND_ITEMS
from graph.test_trace import LOCATION, PATH, at, located_trace
from graph.versus import _fleet_bars, _fleet_rows, _render_traces_comparison, _traces_caption

GPUS = {
    str(index): {"name": "NVIDIA B200", "detail": {"Driver Version": "610.57.04", "CUDA Version": "13.3"}}
    for index in range(8)
}


def trace(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_name=lambda: name,
        get_cpu=lambda: {"sockets": 2, "model": "AMD EPYC 9575F", "numa_domains": 16},
        get_gpus=lambda: GPUS,
        get_metric_name=lambda: "BMC.Server",
    )


def step(kind: str, workers: int, perf: float) -> dict:
    """The metrics of one scaling step, for a benchmark loading <kind> components."""
    return {
        "engine_module": "core",
        "perf_key": "TFLOPS",
        "multi_metric": False,
        "unit": "TFLOPS",
        "unit_name": kind,
        "units": workers if kind == "gpu" else 128,
        "workers": workers,
        "perf": perf,
        "power": 5000.0,
        "clock": 1900.0,
        "cpu_clock": 3000.0,
        "cpu_power": 400.0,
        "temp": 33.0 if kind == "gpu" else None,
        "ipc": 0.5,
        "cov": None,
        "lin_full": 100.0,
    }


def render(*kinds: str) -> str:
    traces = [trace("a"), trace("b")]
    metrics = {
        name: {("job", f"emp{i}", "TFLOPS"): step(kind, 8, 400.0 + 10 * j) for i, kind in enumerate(kinds)}
        for j, name in enumerate(["a", "b"])
    }
    return _render_traces_comparison(
        SimpleNamespace(title=""),
        traces,
        metrics,
        {"a": 128, "b": 128},
        {"a": (1, 8), "b": (1, 8)},
        scope_title="",
        columns_scope="full load",
        aggregate_scope="full-load ratios",
        ref_missing_reason="did not run this benchmark",
    )


def test_gpu_only_describes_the_gpus():
    """A report of GPU benchmarks has no CPU column in its main table."""
    text = render("gpu")

    assert "8x NVIDIA B200, Driver: 610.57.04, CUDA: 13.3   scaling 1->8 GPUs" in text
    header = next(line for line in text.splitlines() if line.startswith("Trace  GPUs"))
    for column in ("Perf/GPU", "Δperf/GPU", "Clock", "Temp", "Linearity"):
        assert column in header
    for column in ("Wrk", "Perf/core", "IPC", "CoV"):
        assert column not in header
    # The host CPU is described apart, in a table per benchmark
    assert "host: 2x AMD EPYC 9575F - 16 NUMA" in text
    host = text.split("Host CPU during core/emp0:")[1].splitlines()[1]
    assert host.split() == ["Trace", "CPU", "power", "Δpower", "Clock", "Δclock", "IPC", "ΔIPC"]
    assert "400W" in text
    assert "3000M" in text
    # 400 TFLOPS on 8 GPUs
    assert "50.0" in text
    assert "Perf/core" not in text
    assert "CoV" not in text


def test_cpu_only_is_unchanged():
    text = render("core")

    assert "2x AMD EPYC 9575F" in text
    assert "128 cores / 16 NUMA" in text
    assert "NVIDIA" not in text
    header = next(line for line in text.splitlines() if line.startswith("Trace  Wrk"))
    for column in ("Perf/core", "IPC", "CoV"):
        assert column in header
    assert "Temp" not in header
    assert "Host CPU during" not in text


def test_mixed_normalizes_each_benchmark_by_what_it_loads():
    text = render("core", "gpu")

    assert "AMD EPYC" in text
    assert "8x NVIDIA B200" in text
    header = next(line for line in text.splitlines() if line.startswith("Trace  Wrk"))
    for column in ("Perf/unit", "Temp"):
        assert column in header


def test_linearity_of_a_single_step_is_not_reported():
    """A benchmark without scaling has no linearity: it must not read as a perfect one."""
    traces = [trace("a"), trace("b")]
    single = step("gpu", 8, 400.0) | {"lin_full": None}
    metrics = {name: {("job", "emp", "TFLOPS"): single} for name in ("a", "b")}
    text = _render_traces_comparison(
        SimpleNamespace(title=""),
        traces,
        metrics,
        {"a": 128, "b": 128},
        {"a": (8, 8), "b": (8, 8)},
        scope_title="",
        columns_scope="full load",
        aggregate_scope="full-load ratios",
        ref_missing_reason="did not run this benchmark",
    )

    lines = text.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("Trace  GPUs"))
    # The two rows of the benchmark table, after its separator
    assert [line.split()[-1] for line in lines[header + 2 : header + 4]] == ["-", "-"]
    assert "+0%" not in text


def test_traces_caption_location():
    """Each trace only gives the places of its location below the ones they share, given by the header."""
    caption = _traces_caption([located_trace(LOCATION), located_trace(LOCATION | {"path": [*PATH[:-2], "A13", "24"]})])
    assert [block.splitlines()[1:3] for block in caption.split("\n\n")] == [
        ["  System   : SRV01 ProLiant DL385 Gen11", "  Location : Rack A12 / Position 23"],
        ["  System   : SRV01 ProLiant DL385 Gen11", "  Location : Rack A13 / Position 24"],
    ]


@pytest.mark.parametrize("other", [at("DE", "FRA1"), None])
def test_traces_caption_location_not_shared(other):
    """Servers not sharing their location, or not all located, give none."""
    assert "Location" not in _traces_caption([located_trace(LOCATION), located_trace(other)])


def test_fleet_rows():
    """The distribution of each metric over a fleet, the max and the min naming their server."""
    agg = {f"SRV{index}": {"dperf": 1.0 + index / 10, "cov": None} for index in range(5)}
    labels, rows, servers = _fleet_rows(list(agg), agg, ["dperf", "cov"])
    assert labels == ["max", "Q3", "median", "Q1", "min"]
    assert [round(row["dperf"], 2) for row in rows] == [1.4, 1.3, 1.2, 1.1, 1.0]
    assert all(row["cov"] is None for row in rows)
    assert servers == [{"dperf": "SRV4"}, {}, {}, {}, {"dperf": "SRV0"}]


def test_fleet_caption():
    """Beyond MAX_LEGEND_ITEMS servers, the servers of a same system are counted, not described one by one."""
    traces = [located_trace(LOCATION) for _ in range(MAX_LEGEND_ITEMS + 1)]
    assert _traces_caption(traces).splitlines()[:3] == [
        f"{MAX_LEGEND_ITEMS + 1} servers (ref):",
        "  System   : ProLiant DL385 Gen11",
        "  Bios     : v3.16",
    ]


def test_fleet_bars():
    """The reference, then the distribution of the traces which ran the benchmark, naming the max and the min."""
    names = [f"SRV{index}" for index in range(6)]
    values = [3.0, 1.0, 2.0, 4.0, 5.0, 0.0]
    labels = [f"{name}\n64 workers" for name in names]
    workers = [64, 64, 64, 64, 64, -1]
    bar_labels, bars = _fleet_bars(names, values, labels, workers)
    assert bar_labels == ["SRV0\n64 workers", "max of 5\nSRV4", "Q3 of 5", "median of 5", "Q1 of 5", "min of 5\nSRV1"]
    assert bars == [3.0, 5.0, 4.0, 3.0, 2.0, 1.0]
