import datetime
import logging
import sys
from datetime import timedelta
from typing import NoReturn


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
