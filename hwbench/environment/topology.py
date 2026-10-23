from __future__ import annotations

import json
import pathlib
import shutil
from collections.abc import Iterator

import jsonschema

from hwbench.utils import helpers as h

from .environment_file import LOCATION_KEYS, location_line

# The name of the copy of the topology file in the output directory
TOPOLOGY_FILE = "topology.json"

# The version of the topology format written by the exporters, and the schema of each version read
TOPOLOGY_VERSION = 1
SCHEMAS = {1: "topology-v1.schema.json"}

# The levels of the hierarchy of the topology, from the widest: the keys of the location,
# but Extra, which has its own section for the servers out of the hierarchy
LEVELS = [key for key in LOCATION_KEYS if key != "Extra"]


def schema(version: int = TOPOLOGY_VERSION) -> dict:
    """The JSON schema of a version of the topology format."""
    return json.loads(schema_path(version).read_text())


def schema_path(version: int = TOPOLOGY_VERSION) -> pathlib.Path:
    return pathlib.Path(__file__).with_name(SCHEMAS[version])


def json_path(path) -> str:
    """Where a value is in the topology, unambiguous whatever the names: '["topology"]["FR"]'."""
    return "".join(f"[{json.dumps(key)}]" for key in path) or "the document"


def error_message(error: jsonschema.ValidationError) -> str:
    """The message of a schema error, the patterns of the names told in words."""
    if error.validator == "pattern":
        return "a name cannot be empty" if error.instance == "" else f"{error.instance!r} has spaces at its ends"
    return error.message


def servers(topology: dict) -> Iterator[tuple[str, dict[str, str]]]:
    """Each serial of a valid topology with its location: the levels named, or Extra."""

    def walk(node, path: list[str]) -> Iterator[tuple[str, list[str]]]:
        if len(path) == len(LEVELS):
            for serial in node:
                yield serial, path
            return
        for name, child in node.items():
            yield from walk(child, [*path, name])

    for serial, path in walk(topology["topology"], []):
        # A level named '' is not known: not set, like an empty key of the [Location] section
        yield serial, {key: name for key, name in zip(LEVELS, path) if name}
    for place, serials in topology["extra"].items():
        for serial in serials:
            yield serial, {"Extra": place}


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

    # What the schema cannot check: a server is at a single place
    places: dict[str, list[dict[str, str]]] = {}
    for serial, location in servers(topology):
        places.setdefault(serial, []).append(location)
    return [
        f"the serial '{serial}' is at several places: {', '.join(repr(location_line(location) or '') for location in locations)}"
        for serial, locations in places.items()
        if len(locations) > 1
    ]


def read_topology(topology_file: str) -> tuple[dict, list[str]]:
    """The topology of a file and what makes it invalid, its reading included."""
    try:
        topology = json.loads(pathlib.Path(topology_file).read_text())
    except (OSError, ValueError) as e:
        return {}, [f"cannot read the topology: {e}"]
    return topology, topology_problems(topology)


def find_location(topology: dict, serial: str) -> dict[str, str] | None:
    """The location of the server of a serial in a valid topology, or None when it is not there."""
    return next((location for found, location in servers(topology) if found == serial), None)


def topology_location(topology_file: str, serial: str) -> dict[str, str]:
    """The location of the target machine in a topology file, found by its serial: stops hwbench when
    the topology is invalid or does not have the serial."""
    topology, problems = read_topology(topology_file)
    if problems:
        h.fatal(
            f"{topology_file}: invalid topology, check it with tools/topology_check.py:\n  " + "\n  ".join(problems)
        )
    location = find_location(topology, serial)
    if location is None:
        h.fatal(f"{topology_file}: the serial '{serial}' of the target machine is neither in the topology nor in extra")
    return location


def save_topology(topology_file: str, out_dir: pathlib.Path) -> None:
    """Copy the topology file in the output directory."""
    out_file = out_dir.joinpath(TOPOLOGY_FILE)
    try:
        shutil.copyfile(topology_file, out_file)
    except OSError as e:
        h.fatal(f"Cannot save the topology file '{topology_file}' as '{out_file}': {e}")
