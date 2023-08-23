import logging
import sys


def fatal(message):
    logging.error(message)
    sys.exit(1)
