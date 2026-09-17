from __future__ import annotations

import datetime
import logging
import sys
from datetime import timedelta
from shutil import which
from typing import NoReturn


class MissingBinary(Exception):
    def __init__(self, binary):
        self.binary = binary

    def __str__(self):
        return f"Binary {self.binary} is not available on the system"


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


def versiontuple(v: str) -> tuple[int, ...]:
    """
    Convert a version string to a tuple of integers that allows very basic version comparisons
    """
    return tuple(map(int, (v.split("."))))
