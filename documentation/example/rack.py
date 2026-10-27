"""Builds the rack of the reference dataset, illustrating the rack graphs of hwgraph --auto-group, from
traces/cdu_comparison.json:

    uv run python documentation/example/rack.py <directory>

It writes a trace per server in <directory>, located in the rack A12, positions 1 to 12:

- 1U servers, two of them with 4 GPUs, the air warmer at the top of the rack;
- a 2U chassis of 4 nodes of 1U at the position 4, and a 2U server at the position 7;
- empty positions between them.

The servers are the recorded host monitoring of cdu_comparison.json, with synthetic differences: each
server is shifted by fixed amounts depending on its position, so that every rendering gives the same
images. Only the metrics the rack graphs read are kept, to keep the traces small.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

SOURCE = pathlib.Path(__file__).parent / "traces" / "cdu_comparison.json"
LEVELS = ["Country", "Datacenter", "Datahall", "Room", "Rack", "Position"]
RACK = ["FR", "PA99", "2", "1", "A12"]
# The contexts read by the rack graphs and the group graphs of --auto-group
CONTEXTS = ("Fans", "PowerConsumption", "Thermal")

# Serial, position, height of the server, height of its chassis, serial of its chassis, GPUs
SERVERS = [
    ("EXAMPLE0101", 1, 1, 1, None, 0),
    ("EXAMPLE0102", 2, 1, 1, None, 0),
    *((f"EXAMPLE0104{node}", 4, 1, 2, "EXAMPLE0104", 0) for node in "ABCD"),
    ("EXAMPLE0107", 7, 2, 2, None, 0),
    ("EXAMPLE0109", 9, 1, 1, None, 4),
    ("EXAMPLE0110", 10, 1, 1, None, 4),
    ("EXAMPLE0112", 12, 1, 1, None, 0),
]
# The load of each server, in degrees added to its components: fixed, unlike a random one
LOADS = [0.5, 2.0, 1.0, 3.0, -0.5, 1.5, 2.5, 0.0, 1.0, -1.0]


def shift(metric: dict, delta: float) -> None:
    for key in ("values", "mean", "min", "max"):
        if key in metric:
            metric[key] = [None if value is None else round(value + delta, 1) for value in metric[key]]


def scale(metric: dict, factor: float) -> None:
    for key in ("values", "mean", "min", "max"):
        if key in metric:
            metric[key] = [None if value is None else round(value * factor, 1) for value in metric[key]]


def server(source: dict, serial: str, position: int, height: int, chassis_height: int, chassis, gpus: int, load):
    trace = copy.deepcopy(source)
    trace["location"] = {"path": [*RACK, str(position)], "separator": "/", "levels": LEVELS}
    dmi = trace["hardware"]["dmi"]
    dmi |= {"serial": serial, "height": height}
    dmi["chassis"] = {"product": "", "serial": chassis or serial, "height": chassis_height}
    trace["environment"]["kernel"]["nodename"] = serial.lower()
    # Warmer air at the top of the rack
    inlet = 0.3 * position
    for bench in trace["bench"].values():
        contexts = bench["monitoring"]["contexts"]
        bench["monitoring"]["contexts"] = {name: contexts[name] for name in CONTEXTS}
        # The power of the package, read by the group graphs, without the one of each core
        power = contexts["PowerConsumption"]
        power["CPU"] = {"package": power["CPU"]["package"]}
        thermal = contexts["Thermal"]
        for metric in thermal["Intake"].values():
            shift(metric, inlet)
        for family in ("CPU", "Memory", "PowerSupply"):
            for metric in thermal[family].values():
                shift(metric, 1.2 * inlet + load)
        # The air leaving the server, warmer than its memory: its Sys Exhaust sensors
        for metric in thermal["SystemBoard"].values():
            shift(metric, 6 + 1.5 * inlet + load / 2)
        # The fans of the recorded server run at 100 %: from half of it, faster when warmer
        for metric in contexts["Fans"]["Fan"].values():
            scale(metric, 0.5 + inlet / 20 + load / 40)
        for metric in power["BMC"].values():
            scale(metric, 1 + load / 40 + inlet / 100)
        if gpus:
            reference = next(iter(thermal["CPU"].values()))
            thermal["GPU"] = {}
            for index in range(gpus):
                metric = copy.deepcopy(reference) | {"name": f"GPU_{index}"}
                shift(metric, 15 + index)
                thermal["GPU"][f"GPU_{index}"] = metric
    return trace


def main() -> None:
    directory = pathlib.Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE.read_text())
    for (serial, position, height, chassis_height, chassis, gpus), load in zip(SERVERS, LOADS):
        trace = server(source, serial, position, height, chassis_height, chassis, gpus, load)
        directory.joinpath(f"{serial}.json").write_text(json.dumps(trace))


if __name__ == "__main__":
    main()
