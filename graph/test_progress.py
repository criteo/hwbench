from graph import common
from graph.common import duration, progress


def test_duration():
    assert [duration(s) for s in (3, 123, 3723)] == ["3s", "2m03s", "1h02m03s"]


def test_time_left(monkeypatch, capsys):
    """The time left comes from the speed of the items done after the first one, and starts again with
    the step."""
    now = [100.0]
    monkeypatch.setattr(common.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(common, "PROGRESS_STARTS", {})
    for done, at in ((10, 100.0), (20, 120.0), (30, 140.0)):
        now[0] = at
        progress("rendering", done, 50, "tasks")
    progress("rendering", 50, 50, "tasks")
    # 10 items in 20 s since the first report: 20 items left take 40 s
    assert capsys.readouterr().out.splitlines() == [
        "rendering: 10/50 tasks",
        "rendering: 20/50 tasks, ETA 1m00s",
        "rendering: 30/50 tasks, ETA 40s",
        "rendering: 50/50 tasks",
    ]
    # The same step starting again does not reuse the speed of the previous run
    now[0] = 1000.0
    progress("rendering", 10, 50, "tasks")
    assert capsys.readouterr().out == "rendering: 10/50 tasks\n"
