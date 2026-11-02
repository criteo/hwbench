"""The ASHRAE TC 9.9 classes of the environment of the servers, from its Thermal Guidelines for Data
Processing Environments, fifth edition (2021), and its Technology Cooling System classes.

A place of the topology, or a CDU, declares a class per family: the narrowest declaration of a
family wins, each family being inherited separately. See documentation/topology.md.
"""

from __future__ import annotations

# The classes of each family, each family limiting its own temperature:
# - air: the air entering the servers (Thermal Guidelines, tables 2.1 and 2.2);
# - primary: the facility water supplied to the CDUs (Thermal Guidelines, table 3.1);
# - secondary: the liquid the CDUs supply to the servers, the Technology Cooling System.
FAMILIES = {
    "air": ["A1", "A2", "A3", "A4", "H1"],
    "primary": ["W17", "W27", "W32", "W40", "W45", "W+"],
    "secondary": ["S30", "S35", "S40", "S45", "S50"],
}


def family(ashrae_class: str) -> str | None:
    """The family of a class, None for an unknown one."""
    return next((name for name, classes in FAMILIES.items() if ashrae_class in classes), None)


def resolve(declarations: list[list[str]]) -> dict[str, str]:
    """The class of each family from declarations ordered from the widest to the narrowest: the
    narrowest declaring a family wins, the families none declares are missing."""
    resolved: dict[str, str] = {}
    for declaration in declarations:
        for ashrae_class in declaration:
            name = family(ashrae_class)
            if name:
                resolved[name] = ashrae_class
    # In the order of the families, whatever the order of the declarations
    return {name: resolved[name] for name in FAMILIES if name in resolved}


def parse(names: list[str]) -> tuple[dict[str, str], list[str]]:
    """The class of each family of a list of classes, like the ashrae key of a CDU, and what makes the
    list invalid: an unknown class, or several classes of a family."""
    classes: dict[str, list[str]] = {}
    problems = []
    for name in names:
        found = family(name)
        if found is None:
            known = ", ".join(known_class for known_classes in FAMILIES.values() for known_class in known_classes)
            problems.append(f"unknown class {name!r}, expecting one of {known}")
        else:
            classes.setdefault(found, []).append(name)
    for same_family in classes.values():
        if len(same_family) > 1:
            problems.append(f"{', '.join(map(repr, same_family))} are classes of the same family, one per family")
    return {name: classes[name][0] for name in FAMILIES if name in classes}, problems


def line(classes: dict[str, str]) -> str:
    """The classes of each family in one line: 'H1 (air), W40 (primary), S35 (secondary)'."""
    return ", ".join(f"{name} ({found})" for found, name in classes.items())
