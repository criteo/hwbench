from __future__ import annotations

import configparser
import pathlib
import re

from hwbench.utils import helpers as h

# The name of the copy of the environment file in the output directory
ENVIRONMENT_FILE = "environment.cfg"

# The section of the environment file locating the server
LOCATION_SECTION = "Location"

# The keys of the location, from the widest to the narrowest, with the label shown before their value
LOCATION_KEYS = {
    "Country": "",
    "Datacenter": "",
    "Datahall": "",
    "Room": "",
    "Rack": "Rack ",
    "U": "U",
    "Extra": "",
}

# A password key, even commented out, as configparser reads it: any case, '=' or ':', or no value
PASSWORD_LINE = re.compile(r"^\s*[#;]?\s*password\s*([=:].*)?$", re.IGNORECASE)


def without_passwords(content: str) -> str:
    """The environment file without its password keys, nor the indented lines continuing their value."""
    lines = []
    in_password = False
    for line in content.splitlines(keepends=True):
        if PASSWORD_LINE.match(line):
            in_password = True
            continue
        # configparser continues a value on the indented lines that follow it
        if in_password and line.strip() and line[0].isspace():
            continue
        in_password = False
        lines.append(line)
    return "".join(lines)


def save_environment_file(environment_file: str, out_dir: pathlib.Path) -> None:
    """Copy the environment file in the output directory, without the passwords of the BMC and the PDUs."""
    out_file = out_dir.joinpath(ENVIRONMENT_FILE)
    try:
        out_file.write_text(without_passwords(pathlib.Path(environment_file).read_text()))
    except OSError as e:
        h.fatal(f"Cannot save the environment file '{environment_file}' as '{out_file}': {e}")


def read_location(environment_file: str) -> dict[str, str]:
    """The keys of the [Location] section set in the environment file, in the order of LOCATION_KEYS.

    A key absent or empty is not set; an unknown key stops hwbench with the valid ones.
    """
    # No interpolation: a '%' in a free text, like Extra, is kept as is
    environment = configparser.ConfigParser(allow_no_value=True, interpolation=None)
    try:
        environment.read_string(pathlib.Path(environment_file).read_text(), environment_file)
    except (OSError, configparser.Error) as e:
        h.fatal(f"Cannot read the environment file '{environment_file}': {e}")
    section = next((name for name in environment.sections() if name.lower() == LOCATION_SECTION.lower()), None)
    if section is None:
        return {}
    # configparser gives the keys in lowercase
    keys = {key.lower(): key for key in LOCATION_KEYS}
    for key in environment.options(section):
        if key not in keys:
            h.fatal(
                f"{environment_file}: unknown key '{key}' in the [{section}] section, expecting {', '.join(LOCATION_KEYS)}"
            )
    values = {key: (environment.get(section, key.lower(), fallback="") or "").strip() for key in LOCATION_KEYS}
    return {key: value for key, value in values.items() if value}


def location_line(location: dict[str, str]) -> str | None:
    """The location of a server in one line, from the widest to the narrowest: 'FR / PA99 / Rack A12 / U23'."""
    if not location:
        return None
    return " / ".join(f"{label}{location[key]}" for key, label in LOCATION_KEYS.items() if key in location)
