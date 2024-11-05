import datetime
import logging
import sys
from datetime import timedelta
from shutil import which
from typing import NoReturn, Optional


def fatal(message) -> NoReturn:
    logging.error(message)
    sys.exit(1)


def time_to_next_sync(safe_start=True):
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
    return (next_sync - now).total_seconds(), next_sync


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
    cpu_list.sort()
    output: list[str] = []
    previous_entry: Optional[int] = cpu_list[0]

    for i in range(1, len(cpu_list)):
        current_entry = cpu_list[i]
        is_immediately_next = current_entry - 1 == cpu_list[i - 1]
        needs_compression = cpu_list[i - 1] != previous_entry

        if not is_immediately_next:
            if needs_compression:
                output.append(f"{previous_entry}-{cpu_list[i-1]}")
            else:
                output.append(str(previous_entry))
            previous_entry = current_entry

        # Specifically handle the last entry in the list
        if i == len(cpu_list) - 1:
            if cpu_list[i] != previous_entry:
                output.append(f"{previous_entry}-{current_entry}")
            else:
                output.append(str(current_entry))

    return ", ".join(output)
