from __future__ import annotations

import json
import os
import pickle

import numpy as np

from graph.trace import Trace
from graph.trace_cache import cache_files, read_cache, remove_cache, write_cache
from hwbench.bench.monitoring_structs import MonitorMetric

TRACE = {
    "bench": {
        "job": {
            "monitoring": {
                "metadata": {"samples_count": 3},
                "contexts": {"Thermal": {"CPU": {"CPU1": {"unit": "Celsius", "mean": [40, 41.5, 42.0]}}}},
                # A window of a CDU that did not answer
                "cdus": {"CDU": {"readings": {"supply": {"mean": [18.0, None, 18.2]}}}},
            },
            "cpu_pin": [0, 1],
        }
    },
    "hardware": {"dmi": {"serial": "SRV01"}},
    "environment": {},
    "config": {},
}


def test_round_trip(tmp_path):
    """A converted trace reads as the original one: its complete series as arrays mapped in memory, its
    series with gaps, its empty ones and its other values as they were."""
    trace = TRACE | {"empty": {"mean": []}, "flags": {"values": [True, False]}}
    files = cache_files(tmp_path, __file__)
    write_cache(trace, *files)
    read = read_cache(*files)
    mean = read["bench"]["job"]["monitoring"]["contexts"]["Thermal"]["CPU"]["CPU1"]["mean"]
    assert isinstance(mean.base, np.memmap)
    assert mean.tolist() == [40.0, 41.5, 42.0]
    assert read["bench"]["job"]["monitoring"]["cdus"]["CDU"]["readings"]["supply"]["mean"] == [18.0, None, 18.2]
    assert read["empty"] == {"mean": []}
    assert read["flags"] == {"values": [True, False]}
    assert read["bench"]["job"]["cpu_pin"] == [0, 1]
    assert read["hardware"] == TRACE["hardware"]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(path.name for path in files)


def test_cache_follows_the_trace(tmp_path):
    """The conversion of a trace changes with the trace file."""
    path = tmp_path / "results.json"
    path.write_text(json.dumps(TRACE))
    files = cache_files(tmp_path / "cache", str(path))
    assert cache_files(tmp_path / "cache", str(path)) == files
    os.utime(path, ns=(0, 0))
    assert cache_files(tmp_path / "cache", str(path)) != files


def test_trace_read_from_cache(tmp_path):
    """A trace is converted once in the cache of the output directory, then read from there by the
    workers: its metrics keep the arrays mapped in memory."""
    path = tmp_path / "results.json"
    path.write_text(json.dumps(TRACE))
    cache = tmp_path / "out" / "cache"
    trace = Trace(str(path))
    trace.use_cache(cache)
    skeleton, data = trace.cache
    assert "trace" not in trace.__dict__
    converted = skeleton.stat().st_mtime_ns

    # Another rendering in the same output directory reads the conversion of the first one
    Trace(str(path)).use_cache(cache)
    assert skeleton.stat().st_mtime_ns == converted

    sent = pickle.loads(pickle.dumps(trace))
    metric = MonitorMetric("CPU1", "Celsius")
    metric.load_from_dict(sent.bench_list()["job"]["monitoring"]["contexts"]["Thermal"]["CPU"]["CPU1"], "CPU1")
    assert isinstance(metric.get_mean().base, np.memmap)
    assert metric.get_mean().tolist() == [40.0, 41.5, 42.0]
    assert sent.get_server_serial() == "SRV01"


def test_metric_with_gaps():
    """A series with gaps, not converted, still gets NaN for its gaps."""
    metric = MonitorMetric("supply", "Celsius")
    metric.load_from_dict({"mean": np.array([18.0, 18.2]), "max": [18.0, None]}, "supply")
    assert metric.get_mean().tolist() == [18.0, 18.2]
    assert metric.get_max()[0] == 18.0
    assert np.isnan(metric.get_max()[1])


def test_remove_cache(tmp_path):
    """The cache of an output directory is deleted after the rendering: the traces are read from their
    files again."""
    path = tmp_path / "results.json"
    path.write_text(json.dumps(TRACE))
    cache = tmp_path / "out" / "cache"
    trace = Trace(str(path))
    trace.use_cache(cache)
    remove_cache([trace], cache)
    assert not cache.exists()
    assert "cache" not in trace.__dict__
    assert trace.bench_list()["job"]["cpu_pin"] == [0, 1]
    assert trace.bench_list()["job"]["monitoring"]["contexts"]["Thermal"]["CPU"]["CPU1"]["mean"] == [40, 41.5, 42.0]
