import logging
import sys

from typing import NoReturn


def fatal(message) -> NoReturn:
    logging.error(message)
    sys.exit(1)
