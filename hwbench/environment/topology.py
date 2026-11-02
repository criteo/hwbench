from __future__ import annotations

import json
import logging
import pathlib
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from hwbench.utils import helpers as h

from . import cooling
from .ashrae import resolve
from .environment_file import DEFAULT_SEPARATOR, Location

# The name of the copy of the topology file in the output directory
TOPOLOGY_FILE = "topology.json"

# The version of the topology format written by the exporters, and the schema of each version read
TOPOLOGY_VERSION = 2
SCHEMAS = {1: "topology-v1.schema.json", 2: "topology-v2.schema.json"}
# The key of a place giving its ASHRAE classes, not a place: the names of places cannot start with '@'
ASHRAE_KEY = "@ashrae"

# The separators proposed when the names of the places hold the one of the topology
OTHER_SEPARATORS = ["|", ">", ",", ";", "::"]


def schema(version: int = TOPOLOGY_VERSION) -> dict:
    """The JSON schema of a version of the topology format."""
    return json.loads(schema_path(version).read_text())


def schema_path(version: int = TOPOLOGY_VERSION) -> pathlib.Path:
    return pathlib.Path(__file__).with_name(SCHEMAS[version])


def json_path(path) -> str:
    """Where a value is in the topology, unambiguous whatever the names: '["topology"]["FR"]'."""
    return "".join(f"[{json.dumps(key)}]" for key in path) or "the document"


def error_message(error: jsonschema.ValidationError) -> str:
    """The message of a schema error, the patterns of the names and the families of classes told in words."""
    # The value and the schema in error: Unset only for the errors the schema does not raise
    instance: Any = error.instance
    error_schema: Any = error.schema
    if error.validator == "pattern":
        if instance == "":
            return "a name cannot be empty"
        # Only the names of places of the version 2 cannot start with '@'
        if instance.startswith("@") and instance == instance.strip():
            return f"{instance!r} starts with '@', kept for the ASHRAE classes of a place"
        return f"{instance!r} has spaces at its ends"
    # A server is a serial or an object: the error of the form it is written in
    if error.validator == "anyOf" and error.context:
        written = [sub for sub in error.context if sub.validator != "type"]
        return error_message(jsonschema.exceptions.best_match(written or error.context))
    if error.validator == "maxContains":
        family = [name for name in instance if name in error_schema["contains"]["enum"]]
        return f"{', '.join(map(repr, family))} are classes of the same family, a place declares one per family"
    return error.message


@dataclass
class TopologyServer:
    """A server of a topology: its serial, its location, its label, the ASHRAE classes it inherits and the
    cooling of its components."""

    serial: str
    location: Location
    label: str | None = None
    # The class of each family of ashrae.FAMILIES the places of the server declare, the narrowest winning
    ashrae: dict[str, str] = field(default_factory=dict)
    # The cooling of each component of cooling.COMPONENTS since the version 2, the one its label declares,
    # air otherwise
    cooling: dict[str, str] = field(default_factory=dict)


def places(topology: dict, node: dict) -> Iterator[tuple[str, dict | list]]:
    """The places a place holds, without its ASHRAE classes: a place of the version 1 can be named '@ashrae'."""
    return ((name, child) for name, child in node.items() if name != ASHRAE_KEY or topology["version"] == 1)


def leaves(topology: dict) -> Iterator[tuple[list[str], list, list[list[str]]]]:
    """Each list of servers of a topology with the path of its places, from the widest, and the ASHRAE
    classes these places declare, from the widest."""

    def walk(node: dict, path: list[str], declarations: list[list[str]]):
        if topology["version"] > 1:
            declarations = [*declarations, node.get(ASHRAE_KEY, [])]
        for name, child in places(topology, node):
            if isinstance(child, list):
                yield [*path, name], child, declarations
            else:
                yield from walk(child, [*path, name], declarations)

    yield from walk(topology["topology"], [], [])


def topology_servers(topology: dict) -> Iterator[TopologyServer]:
    """Each server of a valid topology; a place out of the hierarchy has no levels. A server is its serial,
    or an object giving its serial and its label since the version 2, the labels declaring the cooling of
    the components of their servers, air when they do not."""
    labels = topology.get("labels", {})
    levels = topology.get("levels")
    separator = topology.get("separator", DEFAULT_SEPARATOR)
    for path, entries, declarations in leaves(topology):
        location = Location(path, separator, levels if levels and len(path) == len(levels) else None)
        for entry in entries:
            if isinstance(entry, str):
                entry = {"serial": entry}
            label = entry.get("label")
            components = cooling.resolve(labels.get(label)) if topology["version"] > 1 else {}
            yield TopologyServer(entry["serial"], location, label, resolve(declarations), components)


def servers(topology: dict) -> Iterator[tuple[str, Location]]:
    """Each serial of a valid topology with its location."""
    return ((server.serial, server.location) for server in topology_servers(topology))


def topology_problems(topology) -> list[str]:
    """What makes a topology invalid, each with where it is in the file; empty when valid."""
    version = topology.get("version") if isinstance(topology, dict) else None
    if isinstance(topology, dict) and "version" in topology and version not in SCHEMAS:
        return [f'["version"]: unknown version {version!r}, expecting {", ".join(map(str, SCHEMAS))}']
    validator = jsonschema.Draft202012Validator(schema(version if version in SCHEMAS else TOPOLOGY_VERSION))
    problems = sorted(
        f"{json_path(error.absolute_path)}: {error_message(error)}" for error in validator.iter_errors(topology)
    )
    if problems:
        return problems

    # What the schema cannot check: the depth of the serials, a known place, a server at a single place
    levels = topology.get("levels")
    for path, _, _ in leaves(topology):
        where = json_path(["topology", *path])
        if levels and len(path) not in (1, len(levels)):
            problems.append(
                f"{where}: serials at the level {len(path)}, expecting the {len(levels)} levels "
                f"{' / '.join(levels)}, or a single place out of the hierarchy"
            )
        elif not any(path):
            problems.append(f"{where}: serials without any known place")
    if problems:
        return problems
    # The serials are compared in uppercase, an inventory may not have the case of the DMI
    places: dict[str, list[Location]] = {}
    spelling: dict[str, str] = {}
    for serial, location in servers(topology):
        places.setdefault(serial.upper(), []).append(location)
        spelling.setdefault(serial.upper(), serial)
    return [
        f"the serial '{spelling[serial]}' is at several places: {', '.join(repr(location.line()) for location in locations)}"
        for serial, locations in places.items()
        if len(locations) > 1
    ]


def separator_warnings(topology: dict) -> list[str]:
    """The places of a valid topology whose name holds its separator: their locations cannot be read
    back, each with a separator none of the names holds, to give with "separator"."""
    separator = topology.get("separator", DEFAULT_SEPARATOR)
    names: list[tuple[list[str], str]] = []

    def walk(node: dict, path: list[str]) -> None:
        for name, child in places(topology, node):
            names.append((path, name))
            if isinstance(child, dict):
                walk(child, [*path, name])

    walk(topology["topology"], [])
    found = [(path, name) for path, name in names if separator in name]
    if not found:
        return []
    other = next((other for other in OTHER_SEPARATORS if all(other not in name for _, name in names)), None)
    advice = f'give another one with "separator", like {other!r}' if other else 'give another one with "separator"'
    return [
        f"{json_path(['topology', *path])}: the place {name!r} holds the separator {separator!r}, "
        f"its locations are ambiguous: {advice}"
        for path, name in found
    ]


def label_warnings(topology: dict) -> list[str]:
    """The labels whose cooling the topology declares, but no server has: probably a misspelled label."""
    used = {server.label for server in topology_servers(topology)}
    return [
        f"the label '{label}' declares the cooling of its servers, but no server has it"
        for label in topology.get("labels", {})
        if label not in used
    ]


def read_topology(topology_file: str) -> tuple[dict, list[str]]:
    """The topology of a file and what makes it invalid, its reading included."""
    try:
        topology = json.loads(pathlib.Path(topology_file).read_text())
    except (OSError, ValueError) as e:
        return {}, [f"cannot read the topology: {e}"]
    return topology, topology_problems(topology)


def find_server(topology: dict, serial: str) -> TopologyServer | None:
    """The server of a serial in a valid topology, or None when it is not there.

    The serials are compared in uppercase: an inventory may not have the case the DMI gives."""
    return next((server for server in topology_servers(topology) if server.serial.upper() == serial.upper()), None)


def find_location(topology: dict, serial: str) -> Location | None:
    """The location of the server of a serial in a valid topology, or None when it is not there."""
    server = find_server(topology, serial)
    return server.location if server else None


def load_topology(topology_file: str) -> dict:
    """The topology of a file given to hwbench: stops hwbench when it is invalid."""
    topology, problems = read_topology(topology_file)
    if problems:
        h.fatal(
            f"{topology_file}: invalid topology, check it with tools/topology_check.py:\n  " + "\n  ".join(problems)
        )
    for warning in separator_warnings(topology) + label_warnings(topology):
        logging.warning(f"{topology_file}: {warning}")
    return topology


def topology_location(topology: dict, topology_file: str, serial: str | None) -> Location:
    """The location of the target machine in a valid topology, found by the serial of its DMI, without
    the spaces some firmwares pad it with: stops hwbench when the topology does not have it."""
    serial = (serial or "").strip()
    if not serial:
        h.fatal(f"{topology_file}: the target machine has no serial in its DMI to find it in the topology")
    location = find_location(topology, serial)
    if location is None:
        h.fatal(f"{topology_file}: the serial '{serial}' of the target machine is not in the topology")
    return location


def save_topology(topology_file: str, out_dir: pathlib.Path) -> None:
    """Copy the topology file in the output directory."""
    out_file = out_dir.joinpath(TOPOLOGY_FILE)
    try:
        shutil.copyfile(topology_file, out_file)
    except OSError as e:
        h.fatal(f"Cannot save the topology file '{topology_file}' as '{out_file}': {e}")
