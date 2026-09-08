import sys
from typing import NoReturn


def fatal(reason) -> NoReturn:
    """Print the error and exit 1."""
    sys.stderr.write(f"Fatal: {reason}\n")
    sys.stderr.flush()
    sys.exit(1)
