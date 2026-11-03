import sys
from types import SimpleNamespace

import pytest

from graph import hwgraph
from graph.render_log import RENDERING_LOG, RenderLog


def test_render_log(tmp_path):
    """The log lists what the graphs printed by job then by graph, and counts the errors and warnings."""
    log = RenderLog()
    log.add("cpu_1", "environment of srv01", "Warning: srv01/cpu_1: Missing sample 3, considering 0 watts.\n")
    log.add("cpu_1", "group JP2 / TY15", "Fatal: srv02/cpu_1: missing\ncpu_1: no fans\n")
    log.add("", "comparison reports", "")
    assert (log.errors, log.warnings) == (1, 1)
    assert log.summary() == "1 error, 1 warning"
    log_file = log.write(tmp_path)
    assert log_file == tmp_path / RENDERING_LOG
    assert log_file.read_text().splitlines() == [
        f"hwgraph rendering of {tmp_path}: 1 error, 1 warning",
        "",
        "== cpu_1",
        "-- environment of srv01",
        "   Warning: srv01/cpu_1: Missing sample 3, considering 0 watts.",
        "-- group JP2 / TY15",
        "   Fatal: srv02/cpu_1: missing",
        "   cpu_1: no fans",
    ]
    # A rendering without any message removes the log of an earlier one
    assert RenderLog().write(tmp_path) is None
    assert not log_file.exists()


def failing(reason: str) -> int:
    print("rendering")
    if reason == "full":
        raise OSError(28, "No space left on device")
    if reason == "fatal":
        sys.stderr.write("Fatal: stopped\n")
        sys.exit(1)
    raise ValueError(reason)


def test_task_output_captured(monkeypatch, capsys):
    """A task prints in the log, not on the console; a fatal() or an exception stops its task only."""
    monkeypatch.setattr(hwgraph, "_pool_args", None)
    assert hwgraph._execute_pool_task((failing, "fatal")) == (0, "rendering\nFatal: stopped\n", None)
    rendered, output, abort = hwgraph._execute_pool_task((failing, "broken"))
    assert (rendered, abort) == (0, None)
    assert output.startswith("rendering\nError generating graph: broken\nTraceback")
    assert capsys.readouterr().out == ""


def test_write_error_aborts(monkeypatch):
    """A graph that cannot be written stops the rendering: the error of cairo could not even be sent back to
    the main process, and the next graphs would fail the same way."""
    monkeypatch.setattr(hwgraph, "_pool_args", None)
    rendered, output, abort = hwgraph._execute_pool_task((failing, "full"))
    assert abort == "OSError: [Errno 28] No space left on device"
    assert "Error generating graph: OSError: [Errno 28] No space left on device" in output


def test_rendering_aborted(tmp_path, monkeypatch, capsys):
    """After a write error, the tasks left are not run, the log is written and hwgraph stops with the reason."""
    ran = []

    def rendering(name: str) -> int:
        ran.append(name)
        if name == "full":
            raise OSError(28, "No space left on device")
        return 1

    args = SimpleNamespace(jobs=1, traces=[])
    tasks = [(rendering, "first"), (rendering, "full"), (rendering, "last")]
    with pytest.raises(SystemExit):
        hwgraph._execute_tasks(args, tasks, tmp_path)
    assert ran == ["first", "full"]
    assert "No space left on device" in (tmp_path / RENDERING_LOG).read_text()
    assert (
        "Fatal: rendering aborted after 1 graphs: OSError: [Errno 28] No space left on device"
        in capsys.readouterr().err
    )
