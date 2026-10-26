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
