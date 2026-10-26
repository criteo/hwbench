from __future__ import annotations

import configparser
import dataclasses
import pathlib
import re

from hwbench.utils import helpers as h

# The name of the copy of the environment file in the output directory
ENVIRONMENT_FILE = "environment.cfg"

# The section of the environment file locating the server, and its keys
LOCATION_SECTION = "Location"
LOCATION_KEYS = ("separator", "levels", "location")

# The separator of the values of the location and of the names of its levels, when not given
DEFAULT_SEPARATOR = "/"

# A password key, even commented out, as configparser reads it: any case, '=' or ':', or no value
PASSWORD_LINE = re.compile(r"^\s*[#;]?\s*password\s*([=:].*)?$", re.IGNORECASE)


def without_passwords(content: str) -> str:
    """The environment file without its password keys, nor the indented lines continuing their value."""
    lines = []
    in_password = False
    # The blank and comment lines after a password: configparser continues its value past them
    held: list[str] = []
    for line in content.splitlines(keepends=True):
        if PASSWORD_LINE.match(line):
            in_password = True
            held = []
            continue
        if in_password:
            if not line.strip() or line.lstrip().startswith(("#", ";")):
                held.append(line)
                continue
            # configparser continues a value on the indented lines that follow it
            if line[0].isspace():
                held = []
                continue
        in_password = False
        lines.extend(held)
        held = []
        lines.append(line)
    lines.extend(held)
    return "".join(lines)


def save_environment_file(environment_file: str, out_dir: pathlib.Path) -> None:
    """Copy the environment file in the output directory, without the passwords of the BMC and the PDUs."""
    out_file = out_dir.joinpath(ENVIRONMENT_FILE)
    try:
        out_file.write_text(without_passwords(pathlib.Path(environment_file).read_text()))
    except OSError as e:
        h.fatal(f"Cannot save the environment file '{environment_file}' as '{out_file}': {e}")


@dataclasses.dataclass
class Location:
    """Where a server is: the path of its places, from the widest to the narrowest.

    The levels name the places of the path, when the hierarchy is known: a path of a single place,
    like 'Secret Lab 1', is out of the hierarchy and has no levels. A place '' is not known.
    """

    path: list[str]
    separator: str = DEFAULT_SEPARATOR
    levels: list[str] | None = None

    def places(self) -> list[str]:
        """The known places, each after the name of its level when the levels are known: 'Rack A12'.

        A place holds its value alone, its level giving what it is: '1' is not readable, 'Room 1' is."""
        levels = self.levels or [""] * len(self.path)
        return [f"{level} {place}".strip() for level, place in zip(levels, self.path) if place]

    def line(self) -> str:
        """The location in one line, without the places not known: 'Country FR / Room 1 / Rack A12 / Position 23'."""
        return f" {self.separator} ".join(self.places())

    def to_dict(self) -> dict:
        """The location as kept in results.json."""
        location: dict = {"path": self.path, "separator": self.separator}
        if self.levels is not None:
            location["levels"] = self.levels
        return location

    @classmethod
    def from_dict(cls, location: dict) -> Location:
        return cls(location["path"], location.get("separator", DEFAULT_SEPARATOR), location.get("levels"))


def split(value: str, separator: str) -> list[str]:
    """The values of a key of the location, cut on the separator, without the spaces at their ends."""
    return [part.strip() for part in value.split(separator)]


def read_location(environment_file: str) -> Location | None:
    """The location of the server given by the [Location] section of the environment file, or None.

    The section takes 'location', the path of the places of the server cut by the separator, '/'
    unless 'separator' gives another one, and 'levels', the names of the places, optional. A
    location of a single place is out of the hierarchy; any other must have as many places as
    there are levels. An unknown key, or a location not matching its levels, stops hwbench.
    """
    # No interpolation: a '%' in the name of a place is kept as is
    environment = configparser.ConfigParser(allow_no_value=True, interpolation=None)
    try:
        environment.read_string(pathlib.Path(environment_file).read_text(), environment_file)
    except (OSError, configparser.Error) as e:
        h.fatal(f"Cannot read the environment file '{environment_file}': {e}")
    section = next((name for name in environment.sections() if name.lower() == LOCATION_SECTION.lower()), None)
    if section is None:
        return None
    for key in environment.options(section):
        # The keys of [DEFAULT], like a username shared by the BMC and the PDUs, are in every section
        if key not in LOCATION_KEYS and key not in environment.defaults():
            h.fatal(
                f"{environment_file}: unknown key '{key}' in the [{section}] section, expecting {', '.join(LOCATION_KEYS)}"
            )

    def value(key: str) -> str:
        return (environment.get(section, key, fallback="") or "").strip()

    separator = value("separator") or DEFAULT_SEPARATOR
    if not value("location"):
        return None
    path = split(value("location"), separator)
    if not any(path):
        return None
    if len(path) == 1:
        return Location(path, separator)
    levels = split(value("levels"), separator) if value("levels") else None
    if levels is not None:
        if not all(levels):
            h.fatal(f"{environment_file}: the levels '{value('levels')}' of the [{section}] section have an empty name")
        if len(levels) != len(path):
            h.fatal(
                f"{environment_file}: the location '{value('location')}' of the [{section}] section has {len(path)} places, "
                f"expecting one for each of the {len(levels)} levels '{value('levels')}', or a single one out of the hierarchy"
            )
    return Location(path, separator, levels)
