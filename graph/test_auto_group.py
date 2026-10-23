from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from graph import hwgraph
from graph.auto_group import group_problem, location_groups
from graph.group import place_suffix
from graph.hwgraph import _collect_auto_group_tasks, main
from graph.test_trace import LOCATION, located_trace
from graph.trace import Trace

TRACES = pathlib.Path("documentation/example/traces")


def racks(*racks: str, **extra) -> list:
    """A trace per rack of the cage 1, at the height 20, 21, …"""
    return [
        located_trace(LOCATION | {"Rack": rack, "U": str(20 + height)} | extra) for height, rack in enumerate(racks)
    ]


def directories(traces: list) -> list[tuple[str, int]]:
    return [(group.name(), len(group.traces)) for group in location_groups(traces)]


def test_location_groups():
    """Each place holding several traces is a group, rendered in the directory of its path."""
    assert directories(racks("A12", "A12", "A13", "A13", "A14")) == [
        ("FR/PA99/DH2/Cage_1", 5),
        ("FR/PA99/DH2/Cage_1/Rack_A12", 2),
        ("FR/PA99/DH2/Cage_1/Rack_A13", 2),
    ]


def test_location_groups_single_place():
    """A place holding the same traces as its single subplace is only rendered in the subplace."""
    assert directories(racks("A12", "A12", "A12")) == [("FR/PA99/DH2/Cage_1/Rack_A12", 3)]


def test_location_groups_partial_location():
    """A partial location is a path of its keys set, apart from the complete ones; Extra after them is ignored."""
    partial = [located_trace({"Rack": "A12", "U": str(height), "Extra": "Secret Lab 1"}) for height in (1, 2)]
    assert directories(partial + racks("A12", "A12")) == [
        ("FR/PA99/DH2/Cage_1/Rack_A12", 2),
        ("Rack_A12", 2),
    ]


def test_location_groups_extra_alone():
    """Extra set alone is the place of its servers."""
    traces = [located_trace({"Extra": lab}) for lab in ("Secret Lab 1", "Secret Lab 1", "Secret Lab 2")]
    assert directories(traces) == [("Secret_Lab_1", 2)]


def test_location_groups_without_location():
    """The traces without location, or with a height alone, are not grouped."""
    assert directories([located_trace(None), located_trace(None), located_trace({"U": "1"})]) == []
    assert directories([located_trace(None)] + racks("A12", "A12")) == [("FR/PA99/DH2/Cage_1/Rack_A12", 2)]


def test_location_groups_same_directory(capsys):
    """Two places named alike in ASCII would be rendered in the same directory: hwgraph stops."""
    with pytest.raises(SystemExit):
        location_groups(racks("A 12", "A 12", "A_12", "A_12"))
    assert (
        "auto-group: the places 'FR / PA99 / DH2 / Cage 1 / Rack A 12', 'FR / PA99 / DH2 / Cage 1 / Rack A_12' are all rendered in the directory FR/PA99/DH2/Cage_1/Rack_A_12"
        in capsys.readouterr().err
    )


@pytest.fixture(scope="module")
def cdu_reboot() -> list[dict]:
    return [json.loads((TRACES / name).read_text()) for name in ("cdu_reboot.json", "cdu_reboot_2.json")]


def group_of(tmp_path, results: list[dict]):
    """The group of the rack A12 of two traces of the reference dataset."""
    traces = []
    for index, result in enumerate(results):
        result = json.loads(json.dumps(result)) | {"location": LOCATION | {"U": str(index)}}
        path = tmp_path / f"server-{index}.json"
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), f"server-{index}", "BMC.Server"))
    [group] = location_groups(traces)
    return group


def test_group_problem(tmp_path, cdu_reboot):
    """The servers of a group ran the same benchmarks, with the power metrics added up."""
    assert group_problem(group_of(tmp_path, cdu_reboot)) is None


def test_group_problem_other_benchmarks(tmp_path, cdu_reboot):
    other = json.loads(json.dumps(cdu_reboot[1]))
    other["bench"]["full_cpu_load_1"] = other["bench"]["full_cpu_load_0"]
    assert group_problem(group_of(tmp_path, [cdu_reboot[0], other])) == (
        "server-1 does not have the benchmarks of server-0"
    )


def test_group_problem_other_settings(tmp_path, cdu_reboot):
    other = json.loads(json.dumps(cdu_reboot[1]))
    other["bench"]["full_cpu_load_0"]["workers"] = 1
    assert group_problem(group_of(tmp_path, [cdu_reboot[0], other])) == (
        "Setting full_cpu_load_0/workers does not match between "
        f"{tmp_path / 'server-0.json'} and {tmp_path / 'server-1.json'}"
    )


def test_group_problem_missing_metric(tmp_path, cdu_reboot):
    other = json.loads(json.dumps(cdu_reboot[1]))
    del other["bench"]["full_cpu_load_0"]["monitoring"]["PowerConsumption"]["CPU"]["package"]
    assert group_problem(group_of(tmp_path, [cdu_reboot[0], other])) == (
        "server-1 has no 'CPU/package' metric in full_cpu_load_0"
    )


def test_auto_group_location_header(tmp_path, cdu_reboot):
    """The graphs of a group give the location of its place in their header, even over several racks,
    with the number of its servers, and the name of the place in their file names."""
    traces = []
    for index, rack in enumerate(("A12", "A12", "A13", "A13")):
        result = json.loads(json.dumps(cdu_reboot[index % 2])) | {
            "location": LOCATION | {"Rack": rack, "U": str(index)}
        }
        path = tmp_path / f"server-{index}.json"
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), f"server-{index}", "BMC.Server"))
    args = SimpleNamespace(traces=traces)
    headers = {}
    with patch.object(hwgraph, "_pool_args", args), patch.object(hwgraph, "graph_group_env") as graph_group_env:
        for task, *task_args in _collect_auto_group_tasks(args, tmp_path):
            task(*task_args)
            group_args = graph_group_env.call_args.args[0]
            headers[pathlib.Path(task_args[1]).relative_to(tmp_path / "by_group").as_posix()] = (
                group_args.location,
                place_suffix(group_args),
            )
    assert headers == {
        "FR/PA99/DH2/Cage_1": ("Location: FR / PA99 / DH2 / Cage 1 (4 servers)", "_Cage_1"),
        "FR/PA99/DH2/Cage_1/Rack_A12": ("Location: FR / PA99 / DH2 / Cage 1 / Rack A12 (2 servers)", "_Rack_A12"),
        "FR/PA99/DH2/Cage_1/Rack_A13": ("Location: FR / PA99 / DH2 / Cage 1 / Rack A13 (2 servers)", "_Rack_A13"),
    }
    assert place_suffix(SimpleNamespace()) == ""


def test_auto_group_excludes_same_group(capsys):
    argv = ["hwgraph", "graph", "--auto-traces", "runs::BMC.Server", "--same-group", "--auto-group"]
    with patch("sys.argv", argv), patch("graph.hwgraph.find_auto_traces", return_value=[]), pytest.raises(SystemExit):
        main()
    assert "argument --auto-group: not allowed with argument --same-group" in capsys.readouterr().err
