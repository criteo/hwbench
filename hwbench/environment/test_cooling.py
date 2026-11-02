from __future__ import annotations

from hwbench.environment.cooling import line, resolve


def test_resolve():
    """A component not declared is cooled by air, in the order of the components."""
    assert resolve({"gpu": "liquid", "cpu": "liquid"}) == {"cpu": "liquid", "memory": "air", "gpu": "liquid"}
    assert resolve(None) == {"cpu": "air", "memory": "air", "gpu": "air"}


def test_line():
    assert line(resolve({"cpu": "liquid"})) == "cpu liquid, memory air, gpu air"
