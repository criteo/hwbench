from __future__ import annotations

from hwbench.environment.ashrae import FAMILIES, LIMITS, line, parse, resolve


def test_resolve():
    """Each family is inherited separately, the narrowest declaration winning."""
    assert resolve([["A1", "W40", "S40"], ["A2"], [], ["S35", "H1"]]) == {
        "air": "H1",
        "primary": "W40",
        "secondary": "S35",
    }
    assert resolve([]) == {}


def test_parse():
    assert parse(["S30", "W32"]) == ({"primary": "W32", "secondary": "S30"}, [])
    classes, problems = parse(["A1", "B2", "A2"])
    assert classes == {"air": "A1"}
    assert problems[0].startswith("unknown class 'B2', expecting one of A1, A2, A3, A4, H1, W17")
    assert problems[1] == "'A1', 'A2' are classes of the same family, one per family"


def test_line():
    assert line({"air": "H1", "primary": "W40"}) == "H1 (air), W40 (primary)"


def test_limits():
    """Every class of FAMILIES has its limits."""
    assert list(LIMITS) == [name for classes in FAMILIES.values() for name in classes]
