import numpy as np

from graph.group import statistics_labels


def test_statistics_labels():
    """The curves give their [min; mean; stddev; max], aligned on each other."""
    labels = statistics_labels({"SRV1": np.array([1.0, 3.0]), "SERVER2": np.array([10.0, 30.0])})
    assert labels == {
        "SRV1": "SRV1    [ 1.0;  2.0;  1.0;  3.0]",
        "SERVER2": "SERVER2 [10.0; 20.0; 10.0; 30.0]",
    }
