from __future__ import annotations

import datetime
import logging
import os
import sys
from datetime import timedelta
from shutil import which
from typing import Any, NoReturn


class MissingBinary(Exception):
    def __init__(self, binary):
        self.binary = binary

    def __str__(self):
        return f"Binary {self.binary} is not available on the system"


class MissingHardware(Exception):
    """A device an engine needs is not present on the system."""

    def __init__(self, reason):
        self.reason = reason

    def __str__(self):
        return str(self.reason)


def english_env() -> dict[str, str]:
    """The environment to run a tool in, so its output does not depend on the locale."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    return env


def fatal(message) -> NoReturn:
    logging.error(message)
    sys.exit(1)


def time_to_next_sync(safe_start=True) -> float:
    """A function to resync task on time.
    The safe_start argument indicate we refuse to start if the next sync is too close
    It returns two values :
    - the amount of seconds before the next sync
    - the utc time of the next sync
    """
    now = datetime.datetime.utcnow()
    next_sync = now
    if safe_start:
        next_sync += timedelta(seconds=15)
    # Let's bump to the next minute o'clock
    next_sync += timedelta(seconds=60 - next_sync.second)
    return (next_sync - now).total_seconds()


def is_binary_available(binary_name: str) -> bool:
    """A function to check if a binary is available"""
    return which(binary_name) is not None


def cpu_list_to_range(cpu_list: list[int]) -> str:
    """
    This function takes a list of integers as input and will link them together in a nicely formatted string
    - `[0, 1, 2, 3, 4, 5]` will give `"0-5"`
    - `[0, 4, 2, 3, 7, 8, 9]` will give `"0, 2-4, 7-9"`

    It was made specifically for formatting a CPU cores list
    """
    if not cpu_list:
        return ""

    cpu_list = sorted(cpu_list)
    output: list[str] = []
    start = previous = cpu_list[0]

    for current in cpu_list[1:]:
        if current == previous + 1:
            previous = current
            continue
        output.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = current

    # Flush the last pending range
    output.append(str(start) if start == previous else f"{start}-{previous}")

    return ", ".join(output)


def format_duration(seconds: int) -> str:
    """Return a duration as "1h 42m 00s", hours going beyond a day."""
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02}m {seconds:02}s"


def versiontuple(v: str) -> tuple[int, ...]:
    """
    Convert a version string to a tuple of integers that allows very basic version comparisons
    """
    return tuple(map(int, (v.split("."))))


def parse_range(input: str) -> list[Any]:
    """Parse the range syntax used by configuration directives.

    Space-separated items are groups, and a multi-group input returns a list of
    lists. Inside a group, ',' separates items and 'x-y' expands to an inclusive
    numeric range. Numeric items are converted to int, everything else is kept
    as a string.
    """
    result: list[int | str | list[int]] = []
    # FIXME: implement 'all'
    # group1 group2...
    groups_count = len(input.split(" "))

    for group in input.split(" "):
        # syntax: <x>,<y>
        current_group: list[Any] = []
        # Let's remove the [] if any
        for item in group.split(","):
            # syntax: <x>-<y>
            if "-" in item:
                ranges = item.split("-")
                if len(ranges) != 2:
                    fatal(f"Invalid range '{item}' in '{input}': a range is <first>-<last>")
                if not ranges[0].isnumeric() or not ranges[1].isnumeric():
                    fatal(f"Non-numeric range {ranges} in '{input}'")
                first, last = int(ranges[0]), int(ranges[1])
                if first > last:
                    fatal(f"Reversed range '{item}' in '{input}': write the smaller value first, {last}-{first}")
                current_group.extend(range(first, last + 1))
            else:
                # syntax: <x>
                item_group: str | int = item
                if item.isnumeric():
                    item_group = int(item)
                current_group.append(item_group)
        if groups_count > 1:
            result.append(current_group)
        else:
            result = current_group
    return result
