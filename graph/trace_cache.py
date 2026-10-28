from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
from typing import Any

import numpy as np

# The directory of the output directory holding the traces converted for the rendering
CACHE_DIRECTORY = "cache"
# Changing the layout of the converted traces makes the next renderings convert them again
CACHE_VERSION = 1
# The keys of the series of a metric, one value per window of the monitoring
SERIES = {"values", "mean", "min", "max", "stdev", "samples"}
# The key replacing a series in the skeleton: its offset and its length in the data file
SERIES_REFERENCE = "__series__"


def cache_files(directory: pathlib.Path, filename: str) -> tuple[pathlib.Path, pathlib.Path]:
    """The skeleton and the data files of the conversion of a trace, named after the trace file and
    changing with its path, its size and its modification time."""
    stat = os.stat(filename)
    identity = f"{CACHE_VERSION}:{os.path.abspath(filename)}:{stat.st_size}:{stat.st_mtime_ns}"
    name = f"{pathlib.Path(filename).name}-{hashlib.sha1(identity.encode()).hexdigest()[:16]}"
    return directory.joinpath(f"{name}.json"), directory.joinpath(f"{name}.f64")


def split_series(node: Any, chunks: list[np.ndarray], offset: int) -> tuple[Any, int]:
    """The node without its series, replaced by their position in the concatenation of the chunks.

    An empty series, or one with gaps, stays in the skeleton: the graphs reading the series without
    MonitorMetric skip its None, that a float would turn into NaN."""
    if isinstance(node, dict):
        skeleton: dict[str, Any] = {}
        for key, value in node.items():
            if key in SERIES and isinstance(value, list) and value and all(type(v) in (int, float) for v in value):
                chunks.append(np.array(value, dtype=np.float64))
                skeleton[key] = {SERIES_REFERENCE: [offset, len(value)]}
                offset += len(value)
            else:
                skeleton[key], offset = split_series(value, chunks, offset)
        return skeleton, offset
    if isinstance(node, list):
        items = []
        for value in node:
            item, offset = split_series(value, chunks, offset)
            items.append(item)
        return items, offset
    return node, offset


def join_series(node: Any, data: np.ndarray) -> Any:
    """The skeleton with its series, views of the data."""
    if isinstance(node, dict):
        reference = node.get(SERIES_REFERENCE)
        if reference is not None and len(node) == 1:
            return data[reference[0] : reference[0] + reference[1]]
        return {key: join_series(value, data) for key, value in node.items()}
    if isinstance(node, list):
        return [join_series(value, data) for value in node]
    return node


def write_cache(trace: dict, skeleton_file: pathlib.Path, data_file: pathlib.Path) -> None:
    """Convert a trace: its series in a single file of floats, the rest in a JSON skeleton. Both are
    written under a temporary name then renamed, an interrupted rendering leaving no partial file."""
    skeleton_file.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[np.ndarray] = []
    skeleton, _ = split_series(trace, chunks, 0)
    temporary = data_file.with_name(f"{data_file.name}.{os.getpid()}")
    (np.concatenate(chunks) if chunks else np.zeros(0)).tofile(temporary)
    os.replace(temporary, data_file)
    # The skeleton last: its presence tells the conversion is complete
    temporary = skeleton_file.with_name(f"{skeleton_file.name}.{os.getpid()}")
    temporary.write_text(json.dumps(skeleton))
    os.replace(temporary, skeleton_file)


def remove_cache(traces: list, directory: pathlib.Path) -> None:
    """Delete the cache of an output directory after its rendering: the traces are read from their files
    again."""
    for trace in traces:
        trace.forget_cache()
    shutil.rmtree(directory, ignore_errors=True)


def read_cache(skeleton_file: pathlib.Path, data_file: pathlib.Path) -> dict:
    """A converted trace, its series mapped in memory: the processes reading it share its pages instead
    of each holding a copy of it."""
    # An empty file cannot be mapped
    data = np.memmap(data_file, dtype=np.float64, mode="r") if data_file.stat().st_size else np.zeros(0)
    return join_series(json.loads(skeleton_file.read_bytes()), data)
