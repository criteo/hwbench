import sys


def fatal(reason):
    """Print the error and exit 1."""
    sys.stderr.write("Fatal: {}\n".format(reason))
    sys.stderr.flush()
    sys.exit(1)
