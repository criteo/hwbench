import sys
from typing import NoReturn


def fatal(reason) -> NoReturn:
    """Print the error and exit 1."""
    sys.stderr.write(f"Fatal: {reason}\n")
    sys.stderr.flush()
    sys.exit(1)


def context_header(args) -> str:
    """The line of the contexts of the runs, under the line naming the benchmark of a header, or nothing."""
    return f"\n{args.context}" if getattr(args, "context", None) else ""


def location_header(args) -> str:
    """The line of the location shared by the servers, under the line of the contexts of a header
    of several servers, or nothing: a header of a single server gives its location under its serial."""
    return f"\n{args.location}" if getattr(args, "location", None) else ""
