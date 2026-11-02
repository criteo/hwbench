"""The cooling of the components of the servers: by the air of the room, or by a liquid, like a cold plate.

The topology declares it per label: the servers of a label share the cooling of their components, a
component it does not declare, or a server without a declared label, being cooled by air. See
documentation/topology.md.
"""

from __future__ import annotations

# The components hwbench monitors whose cooling a label declares, and how each can be cooled
COMPONENTS = ["cpu", "memory", "gpu"]
MODES = ["air", "liquid"]
# The cooling of a component a label does not declare
DEFAULT_MODE = "air"


def resolve(declared: dict[str, str] | None) -> dict[str, str]:
    """The cooling of every component of COMPONENTS, in its order: the one declared, air otherwise."""
    declared = declared or {}
    return {component: declared.get(component, DEFAULT_MODE) for component in COMPONENTS}


def line(cooling: dict[str, str]) -> str:
    """The cooling of each component in one line: 'cpu liquid, memory air, gpu liquid'."""
    return ", ".join(f"{component} {mode}" for component, mode in cooling.items())
