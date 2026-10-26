import numpy as np

from graph.group import named_servers, round_step, statistics_labels


def test_statistics_labels():
    """The curves give their [min; mean; stddev; max], aligned on each other."""
    labels = statistics_labels({"SRV1": np.array([1.0, 3.0]), "SERVER2": np.array([10.0, 30.0])})
    assert labels == {
        "SRV1": "SRV1    [ 1.0;  2.0;  1.0;  3.0]",
        "SERVER2": "SERVER2 [10.0; 20.0; 10.0; 30.0]",
    }


def test_named_servers():
    """Every server is named when the legend holds them, else the highest and the lowest means fill it."""
    few = {f"SRV{index}": np.array([float(index)]) for index in range(4)}
    assert named_servers(few, 4) == (list(few), [])
    fleet = {f"SRV{index}": np.array([float(index), 1.0]) for index in range(10)}
    assert named_servers(fleet, 6) == (["SRV9", "SRV8", "SRV7"], ["SRV1", "SRV0"])
    assert named_servers(fleet, 1) == (["SRV9"], ["SRV0"])


def test_round_step():
    """The smallest round step keeping up to 15 ticks: precise for a rack, and for a site."""
    assert round_step(4336.0) == 500
    assert round_step(1306.2) == 100
    assert round_step(69376.0) == 5000
    assert round_step(150000.0) == 10000
    assert round_step(0) == 1.0


def test_human_format():
    """1000 is shown 1.00K, as the values above it."""
    from graph.graph import Graph

    graph = Graph.__new__(Graph)
    assert [graph.human_format(value) for value in (999.0, 1000.0, 1500.0, 1e6)] == [
        "999.00",
        "1.00K",
        "1.50K",
        "1.00M",
    ]


def test_zero_is_not_merged_with_the_frame(tmp_path):
    """The axes starting at 0 leave a margin before it, without any negative tick shown."""
    from types import SimpleNamespace

    from graph.graph import Graph

    args = SimpleNamespace(width=1920, height=1080, title="", format="png", engine="cairo", dpi=100, verbose=False)
    graph = Graph(args, "title", "x", "y", tmp_path, "zero")
    graph.get_ax().plot([0, 600], [0, 500])
    graph.prepare_axes(30, 5, (None, 50, 25))
    # 2% of 670 workers would be beyond the step of 4 of the minor ticks: the margin stays under it
    workers = Graph(args, "title", "x", "y", tmp_path, "workers")
    workers.get_ax().plot([32, 670], [1, 2])
    workers.prepare_axes(8, 4)
    assert -4 < workers.get_ax().get_xlim()[0] < 0
    for limits, ticks in (
        (graph.get_ax().get_xlim(), graph.get_ax().get_xticks()),
        (graph.get_ax().get_ylim(), graph.get_ax().get_yticks()),
    ):
        assert limits[0] < 0
        assert all(tick >= 0 for tick in ticks if limits[0] <= tick <= limits[1])
