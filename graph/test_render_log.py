import os
import pathlib
import subprocess
import sys
import time
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


def busy(pid_file: str) -> int:
    """A task still rendering when the rendering stops: its worker must be stopped too."""
    pathlib.Path(pid_file).write_text(str(os.getpid()))
    time.sleep(60)
    return 1


def full_once_busy(pid_file: str) -> int:
    """A write error, once the other worker is busy."""
    while not pathlib.Path(pid_file).exists():
        time.sleep(0.01)
    raise OSError(28, "No space left on device")


def test_rendering_aborted_with_workers(tmp_path, capsys):
    """After a write error, the workers still rendering are stopped. shutdown() forgets them: stopping
    them crashed with AttributeError: 'NoneType' object has no attribute 'values'."""
    pid_file = tmp_path / "busy.pid"
    args = SimpleNamespace(jobs=2, traces=[], engine="Agg")
    tasks = [(busy, str(pid_file)), (full_once_busy, str(pid_file))]
    with pytest.raises(SystemExit):
        hwgraph._execute_tasks(args, tasks, tmp_path)
    assert "No space left on device" in (tmp_path / RENDERING_LOG).read_text()
    assert "Fatal: rendering aborted after 0 graphs: OSError: [Errno 28]" in capsys.readouterr().err
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pathlib.Path(f"/proc/{pid}").exists():
        time.sleep(0.05)
    assert not pathlib.Path(f"/proc/{pid}").exists()


PARENT = """
import multiprocessing, os, sys, time
from graph.hwgraph import die_with_parent

def worker(parent, pid_file):
    die_with_parent(parent)
    open(pid_file, "w").write(str(os.getpid()))
    time.sleep(60)

if __name__ == "__main__":
    process = multiprocessing.get_context(sys.argv[2]).Process(target=worker, args=(os.getpid(), sys.argv[1]))
    process.start()
    while not os.path.exists(sys.argv[1]):
        time.sleep(0.01)
    # The main process dies without stopping its worker, as when killed for lack of memory
    os._exit(0)
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is a Linux feature")
def test_worker_dies_with_parent(tmp_path):
    """A worker whose main process died is killed: orphan workers held 28 GB after renderings stopped.
    Started as the workers of the rendering: with forkserver, the default since Python 3.14, the
    worker took the fork server, its parent, for a dead main process and exited at once."""
    pid_file = tmp_path / "worker.pid"
    # A file, not -c: a spawned worker imports the main module to find its function
    script = tmp_path / "parent.py"
    script.write_text(PARENT)
    env = {**os.environ, "PYTHONPATH": str(pathlib.Path(__file__).parent.parent)}
    subprocess.run(
        [sys.executable, str(script), str(pid_file), hwgraph.WORKERS_START_METHOD], check=True, timeout=30, env=env
    )
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pathlib.Path(f"/proc/{pid}").exists():
        time.sleep(0.05)
    assert not pathlib.Path(f"/proc/{pid}").exists()
