from __future__ import annotations

import json
import pathlib

import pytest

from graph.auto_traces import (
    AutoTraces,
    find_auto_traces,
    find_trace_files,
    list_contexts,
    parse_auto_traces,
    print_contexts,
)
from graph.trace import context_line
from hwbench.utils.archive import create_output_archive

REFERENCE = pathlib.Path("documentation/example/traces/numa.json")


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(REFERENCE.read_text())


def run(directory: pathlib.Path, reference: dict, serial: str, context: str | None, archive: bool = False):
    """An output directory of hwbench for a server, in a context, optionally archived next to it."""
    trace = json.loads(json.dumps(reference))
    trace["hardware"]["dmi"]["serial"] = serial
    if context:
        trace["context"] = context
    directory.mkdir(parents=True)
    (directory / "results.json").write_text(json.dumps(trace))
    if archive:
        create_output_archive(directory, serial, "20261022120000")


@pytest.fixture
def runs(tmp_path, reference) -> pathlib.Path:
    run(tmp_path / "hwbench-out-1", reference, "SRV01", "bios-v2", archive=True)
    run(tmp_path / "other" / "hwbench-out-2", reference, "SRV02", "bios-v2")
    run(tmp_path / "hwbench-out-3", reference, "SRV01", "bios-v1")
    run(tmp_path / "old" / "hwbench-out-4", reference, "SRV03", None)
    (tmp_path / "misc").mkdir()
    (tmp_path / "misc" / "results.json").write_text('{"not": "hwbench"}')
    return tmp_path


def test_parse_auto_traces():
    """The context runs from the first to the last ':', so it can hold one."""
    assert parse_auto_traces("runs:bios-v2:CPU.package") == (pathlib.Path("runs"), "bios-v2", "CPU.package")
    assert parse_auto_traces("runs:paste: new:BMC.Server") == (pathlib.Path("runs"), "paste: new", "BMC.Server")
    assert parse_auto_traces("runs::CPU.package") == (pathlib.Path("runs"), None, "CPU.package")
    for value in ["runs:CPU.package", ":bios-v2:CPU.package", "runs:bios-v2:"]:
        with pytest.raises(SystemExit):
            parse_auto_traces(value)


def test_archive_replaces_its_output_directory(runs):
    """An archive and the output directory it compresses next to it are the same run."""
    files = [str(path.relative_to(runs)) for path in find_trace_files(runs)]
    assert files == [
        "hwbench-SRV01-20261022120000.tar.xz",
        "hwbench-out-3/results.json",
        "misc/results.json",
        "old/hwbench-out-4/results.json",
        "other/hwbench-out-2/results.json",
    ]


def test_list_contexts(runs, capsys):
    contexts = list_contexts(runs)
    assert set(contexts) == {"bios-v1", "bios-v2", None}
    assert sorted(trace.server_name() for trace in contexts["bios-v2"]) == ["SRV01", "SRV02"]
    assert [trace.server_name() for trace in contexts[None]] == ["SRV03"]
    assert "misc/results.json: not a trace of hwbench" in capsys.readouterr().out

    print_contexts(runs)
    out = capsys.readouterr().out
    assert "bios-v1: 1 trace\n" in out
    assert "bios-v2: 2 traces\n" in out
    assert "1 trace without context" in out


def test_find_auto_traces(runs):
    """The traces of the context are named after their server."""
    [auto] = find_auto_traces(f"{runs}:bios-v2:CPU.package")
    assert [trace.get_name() for trace in auto.traces] == ["SRV01", "SRV02"]
    assert all(trace.get_metric_name() == "CPU.package" for trace in auto.traces)
    assert auto.description()[1:] == [
        f"SRV01  {runs / 'hwbench-SRV01-20261022120000.tar.xz'}",
        f"SRV02  {runs / 'other' / 'hwbench-out-2' / 'results.json'}",
    ]
    assert context_line(auto.traces) == "Context: bios-v2"


def test_output_directory_name():
    """The context gives a subdirectory of --outdir in ASCII, without space nor unusual character."""
    for context, name in [
        ("bios-v2", "bios-v2"),
        ("bios tuning", "bios_tuning"),
        ("paste: new / fans 100%", "paste_new_fans_100"),
        ("pâte thermique été", "pate_thermique_ete"),
        ("  ../v1.2  ", "v1.2"),
    ]:
        assert AutoTraces(pathlib.Path("runs"), context, []).output_directory_name() == name
    with pytest.raises(SystemExit):
        AutoTraces(pathlib.Path("runs"), "日本", []).output_directory_name()


def test_auto_traces_every_context(runs, reference, capsys):
    """Without context, every context is rendered, then the traces without context together."""
    autos = find_auto_traces(f"{runs}::CPU.package")
    assert [(auto.context, [trace.get_name() for trace in auto.traces]) for auto in autos] == [
        ("bios-v1", ["SRV01"]),
        ("bios-v2", ["SRV01", "SRV02"]),
        (None, ["SRV03"]),
    ]
    assert [auto.output_directory_name() for auto in autos] == ["bios-v1", "bios-v2", "no_context"]
    assert autos[2].description()[0] == f"Traces without context found in {runs}:"
    assert context_line(autos[2].traces) is None

    # A context named like the directory of the traces without context would render over them
    run(runs / "hwbench-out-8", reference, "SRV01", "no context")
    with pytest.raises(SystemExit):
        find_auto_traces(f"{runs}::CPU.package")
    assert (
        "the contexts 'no context', the traces without context are all rendered in the directory no_context"
        in capsys.readouterr().err
    )

    # Two contexts giving the same subdirectory would render over each other
    (runs / "hwbench-out-8" / "results.json").unlink()
    run(runs / "hwbench-out-6", reference, "SRV01", "bios v2")
    run(runs / "hwbench-out-7", reference, "SRV01", "bios:v2")
    with pytest.raises(SystemExit):
        find_auto_traces(f"{runs}::CPU.package")
    assert "the contexts 'bios v2', 'bios:v2' are all rendered in the directory bios_v2" in capsys.readouterr().err


def test_auto_traces_duplicated_server(runs, reference, capsys):
    """The same server found twice with the same context stops hwgraph with the files involved."""
    run(runs / "again" / "hwbench-out-5", reference, "SRV02", "bios-v2")
    with pytest.raises(SystemExit):
        find_auto_traces(f"{runs}:bios-v2:CPU.package")
    assert "SRV02 is found 2 times with the context 'bios-v2'" in capsys.readouterr().err


def test_auto_traces_unknown_context(runs, capsys):
    with pytest.raises(SystemExit):
        find_auto_traces(f"{runs}:bios-v9:CPU.package")
    err = capsys.readouterr().err
    assert "no trace with the context 'bios-v9'" in err
    assert "contexts found: 'bios-v1', 'bios-v2'" in err


def test_context_line(runs):
    """Traces of different contexts give the context of each, traces without context none."""
    contexts = list_contexts(runs)
    first, second = contexts["bios-v1"][0], contexts["bios-v2"][0]
    first.logical_name, second.logical_name = "before", "after"
    assert context_line([first, second]) == "Contexts: before: bios-v1, after: bios-v2"
    assert context_line(contexts[None]) is None
