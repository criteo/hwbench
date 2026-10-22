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
