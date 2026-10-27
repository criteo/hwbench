from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from graph import hwgraph
from graph.auto_group import group_problem, location_groups
from graph.group import place_suffix
from graph.hwgraph import _collect_auto_group_tasks, auto_group_tree, main
from graph.test_trace import LOCATION, PATH, at, located_trace
from graph.trace import Trace

TRACES = pathlib.Path("documentation/example/traces")


def racks(*racks: str) -> list:
    """A trace per rack of the room 1, at the position 20, 21, …"""
    return [
        located_trace(LOCATION | {"path": [*PATH[:4], rack, str(20 + position)]}) for position, rack in enumerate(racks)
    ]


def directories(traces: list) -> list[tuple[str, int]]:
    return [(group.name(), len(group.traces)) for group in location_groups(traces)]


def test_location_groups():
    """Each place holding several traces is a group, rendered in the directory of its path."""
    assert directories(racks("A12", "A12", "A13", "A13", "A14")) == [
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1", 5),
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12", 2),
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A13", 2),
    ]


def test_location_groups_single_place():
    """A place holding the same traces as its single subplace is only rendered in the subplace."""
    assert directories(racks("A12", "A12", "A12")) == [("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12", 3)]


def test_location_groups_same_position():
    """The nodes of a chassis share its whole location: their position is their group."""
    traces = [located_trace(LOCATION), located_trace(LOCATION), *racks("A12")]
    assert directories(traces) == [
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12", 3),
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12/Position_23", 2),
    ]


def test_location_groups_other_hierarchies():
    """The paths are compared whatever their levels and their length."""
    traces = [located_trace(at("PA3", "A12", "1")), located_trace(at("PA3", "A12")), *racks("A12", "A12")]
    assert directories(traces) == [("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12", 2), ("PA3/A12", 2)]


def test_location_groups_other_levels():
    """The levels name the places only when all their servers name them the same way."""
    traces = [*racks("A12"), located_trace(LOCATION | {"levels": ["Country", "DC", "DH", "Room", "Rack", "Position"]})]
    assert directories(traces) == [("FR/PA99/2/1/A12", 2)]


def test_location_groups_unknown_places():
    """A place not known is not a group, the known ones after it are."""
    traces = [located_trace(at("FR", "", "A12", str(position))) for position in (1, 2)]
    traces.append(located_trace(at("FR", "", "A13", "1")))
    assert directories(traces) == [("FR", 3), ("FR/A12", 2)]


def test_location_groups_out_of_the_hierarchy():
    """A location of a single place is the place of its servers."""
    traces = [located_trace(at(lab)) for lab in ("Secret Lab 1", "Secret Lab 1", "Secret Lab 2")]
    assert directories(traces) == [("Secret_Lab_1", 2)]


def test_location_groups_without_location():
    """The traces without location are not grouped."""
    assert directories([located_trace(None), located_trace(None)]) == []
    assert directories([located_trace(None), *racks("A12", "A12")]) == [
        ("Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12", 2)
    ]


def test_location_groups_same_directory(capsys):
    """Two places named alike in ASCII would be rendered in the same directory: hwgraph stops."""
    with pytest.raises(SystemExit):
        location_groups(racks("A 12", "A 12", "A_12", "A_12"))
    assert (
        "auto-group: the places 'Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A 12', 'Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A_12' are all rendered in the directory Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A_12"
        in capsys.readouterr().err
    )


@pytest.fixture(scope="module")
def cdu_reboot() -> list[dict]:
    return [json.loads(TRACES.joinpath(name).read_text()) for name in ("cdu_reboot.json", "cdu_reboot_2.json")]


def group_of(tmp_path, results: list[dict]):
    """The group of the rack A12 of two traces of the reference dataset."""
    traces = []
    for index, result in enumerate(results):
        result = json.loads(json.dumps(result)) | {"location": LOCATION | {"path": [*PATH[:-1], str(index)]}}
        path = tmp_path.joinpath(f"server-{index}.json")
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
        f"{tmp_path.joinpath('server-0.json')} and {tmp_path.joinpath('server-1.json')}"
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
            "location": LOCATION | {"path": [*PATH[:4], rack, str(index)]}
        }
        path = tmp_path.joinpath(f"server-{index}.json")
        path.write_text(json.dumps(result))
        traces.append(Trace(str(path), f"server-{index}", "BMC.Server"))
    args = SimpleNamespace(traces=traces, verbose=False)
    headers = {}
    with patch.object(hwgraph, "_pool_args", args), patch.object(hwgraph, "graph_group_env") as graph_group_env:
        for task, *task_args in _collect_auto_group_tasks(args, tmp_path):
            # The racks also render their rack view, not a graph of the group
            if task is not hwgraph._task_group:
                continue
            task(*task_args)
            group_args = graph_group_env.call_args.args[0]
            headers[pathlib.Path(task_args[1]).relative_to(tmp_path.joinpath("by_group")).as_posix()] = (
                group_args.location,
                place_suffix(group_args),
            )
    assert headers == {
        "Country_FR/Datacenter_PA99/Datahall_2/Room_1": (
            "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 (4 servers)",
            "_Room_1",
        ),
        "Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12": (
            "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 (2 servers)",
            "_Rack_A12",
        ),
        "Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A13": (
            "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 (2 servers)",
            "_Rack_A13",
        ),
    }
    assert place_suffix(SimpleNamespace()) == ""


def test_auto_group_excludes_same_group(capsys):
    argv = ["hwgraph", "graph", "--auto-traces", "runs::BMC.Server", "--same-group", "--auto-group"]
    with patch("sys.argv", argv), patch("graph.hwgraph.find_auto_traces", return_value=[]), pytest.raises(SystemExit):
        main()
    assert "argument --auto-group: not allowed with argument --same-group" in capsys.readouterr().err


def test_auto_group_tree():
    """The groups as a tree, each under the narrowest group holding it, with its number of servers."""
    traces = racks("A12", "A12", "A13", "A13", "A14")
    groups = location_groups(traces)
    rendered = {groups[2].name(): "not rendered, CZ02 does not have the benchmarks of CZ01"}
    assert auto_group_tree(groups, rendered) == [
        "  Country_FR/Datacenter_PA99/Datahall_2/Room_1     5 servers",
        "    Rack_A12                                       2 servers",
        "    Rack_A13                                       2 servers, not rendered, CZ02 does not have the benchmarks of CZ01",
    ]
    assert auto_group_tree(groups[1:2], {}, verbose=True) == [
        "  Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12     2 servers",
        "    SRV01, SRV01",
    ]
