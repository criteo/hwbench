from __future__ import annotations

import io
import json
import pathlib
import tarfile

import pytest
from trace_topology import main

from hwbench.utils.archive import create_output_archive

SAMPLE = pathlib.Path(__file__).parents[1].joinpath("topology.json")
SAMPLE_LOCATION = {
    "path": ["FR", "PA99", "2", "1", "A13", "10"],
    "separator": "/",
    "levels": ["Country", "Datacenter", "Datahall", "Room", "Rack", "Position"],
}


def trace(serial: str, location: dict | None = None) -> dict:
    results = {"environment": {}, "hardware": {"dmi": {"serial": serial}}, "bench": {}, "config": {}}
    if location:
        results["location"] = location
    return results


def output_directory(tmp_path: pathlib.Path, results: dict, topology: str | None = None) -> pathlib.Path:
    out = tmp_path.joinpath("hwbench-out-20261102101436")
    out.mkdir()
    out.joinpath("results.json").write_text(json.dumps(results))
    out.joinpath("other-stdout").write_text("kept")
    if topology:
        out.joinpath("topology.json").write_text(topology)
    return out


def read_archive(archive: pathlib.Path) -> dict[str, bytes]:
    with tarfile.open(archive) as source:
        return {member.name: source.extractfile(member).read() for member in source if member.isfile()}  # type: ignore[union-attr]


@pytest.fixture
def version_1(tmp_path) -> pathlib.Path:
    """The sample without its ASHRAE classes nor its labels, in the version 1."""
    topology = json.loads(SAMPLE.read_text())
    topology["version"] = 1
    del topology["labels"]
    del topology["topology"]["FR"]["PA99"]["@ashrae"]
    room = topology["topology"]["FR"]["PA99"]["2"]["1"]
    del room["@ashrae"]
    del room["A13"]["@ashrae"]
    room["A13"]["10"] = ["NODE0001", "NODE0002", "NODE0003", "NODE0004"]
    path = tmp_path.joinpath("topology-v1.json")
    path.write_text(json.dumps(topology))
    return path


def test_archive_to_version_2(tmp_path, version_1, capsys):
    """An archive run with a topology of the version 1 gets the label, the classes and the cooling, and the new
    topology."""
    out = output_directory(tmp_path, trace("NODE0001", SAMPLE_LOCATION), version_1.read_text())
    archive = create_output_archive(out, "NODE0001", "20261102101436")
    assert main([str(SAMPLE), str(tmp_path)]) == 0
    files = read_archive(archive)
    assert json.loads(files[f"{out.name}/results.json"])["location"] == {
        **SAMPLE_LOCATION,
        "label": "db-01",
        "ashrae": {"air": "H1", "primary": "W40", "secondary": "S35"},
        "cooling": {"cpu": "liquid", "memory": "liquid", "gpu": "air"},
    }
    assert files[f"{out.name}/topology.json"] == SAMPLE.read_bytes()
    assert files[f"{out.name}/other-stdout"] == b"kept"
    # The output directory archived next to it is the same run: only the archive is written
    assert json.loads(out.joinpath("results.json").read_text())["location"] == SAMPLE_LOCATION
    assert capsys.readouterr().out == (
        f"{archive}: NODE0001: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10, "
        "label db-01, ASHRAE H1 (air), W40 (primary), S35 (secondary), cooling cpu liquid, memory liquid, gpu air\n"
    )
    assert main([str(SAMPLE), str(archive)]) == 0
    assert capsys.readouterr().out == f"{archive}: NODE0001: unchanged\n"


def test_results_to_version_1(tmp_path, version_1, capsys):
    """A topology of the version 1 removes the label, the classes and the cooling of a results.json."""
    location = {**SAMPLE_LOCATION, "label": "db-01", "ashrae": {"air": "H1"}, "cooling": {"cpu": "liquid"}}
    out = output_directory(tmp_path, trace("NODE0001", location), SAMPLE.read_text())
    assert main([str(version_1), str(out.joinpath("results.json"))]) == 0
    assert json.loads(out.joinpath("results.json").read_text())["location"] == SAMPLE_LOCATION
    assert out.joinpath("topology.json").read_text() == version_1.read_text()
    assert "no label, no ASHRAE classes, no cooling" in capsys.readouterr().out


def test_moved_and_without_topology(tmp_path, capsys):
    """A trace run without topology gets its location, and the copy of the topology in its archive."""
    out = output_directory(tmp_path, trace("LAB0001"))
    archive = create_output_archive(out, "LAB0001", "20261102101436")
    previous = {"path": ["Secret Lab 2"], "separator": "/"}
    tmp_path.joinpath("other").mkdir()
    other = output_directory(tmp_path.joinpath("other"), trace("LAB0002", previous))
    assert main([str(SAMPLE), str(archive), str(other)]) == 0
    files = read_archive(archive)
    assert json.loads(files[f"{out.name}/results.json"])["location"] == {
        "path": ["Secret Lab 1"],
        "separator": "/",
        "cooling": {"cpu": "air", "memory": "air", "gpu": "air"},
    }
    assert files[f"{out.name}/topology.json"] == SAMPLE.read_bytes()
    assert "Secret Lab 1, moved from Secret Lab 2, no label" in capsys.readouterr().out


def test_dry_run(tmp_path, capsys):
    out = output_directory(tmp_path, trace("NODE0002", SAMPLE_LOCATION))
    content = out.joinpath("results.json").read_text()
    assert main([str(SAMPLE), "--dry-run", str(out)]) == 0
    assert out.joinpath("results.json").read_text() == content
    assert not out.joinpath("topology.json").exists()
    assert "label db-02" in capsys.readouterr().out


def test_unknown_serial(tmp_path, capsys):
    out = output_directory(tmp_path, trace("UNKNOWN", SAMPLE_LOCATION))
    content = out.joinpath("results.json").read_text()
    assert main([str(SAMPLE), str(out)]) == 1
    assert out.joinpath("results.json").read_text() == content
    assert "the serial 'UNKNOWN' of its server is not in the topology, unchanged" in capsys.readouterr().err


def test_not_a_trace(tmp_path, capsys):
    broken = tmp_path.joinpath("hwbench-broken.tar.xz")
    with tarfile.open(broken, "w:xz") as archive:
        data = b"{}"
        member = tarfile.TarInfo("out/results.json")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    assert main([str(SAMPLE), str(broken)]) == 1
    assert f"{broken}: not a trace of hwbench, unchanged" in capsys.readouterr().err


def test_invalid_topology(tmp_path, capsys):
    invalid = tmp_path.joinpath("topology.json")
    invalid.write_text(json.dumps({"version": 3, "topology": {}}))
    assert main([str(invalid), str(tmp_path)]) == 1
    assert "invalid topology, check it with tools/topology_check.py" in capsys.readouterr().err
