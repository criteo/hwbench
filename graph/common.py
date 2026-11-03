import os
import sys
import time
from typing import NoReturn

# The processes rendering the graphs, or reading the traces, by default
DEFAULT_JOBS = (os.cpu_count() or 1) // 2 or 1

# The width of the progress bars, in characters
PROGRESS_WIDTH = 40
# The time and the number of items done when each step reported its first item, to estimate the time left
PROGRESS_STARTS: dict[str, tuple[float, int]] = {}


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


def cdu_header(args) -> str:
    """The lines of the CDUs shared by the servers, under the line of their location in a header of
    several servers, or nothing: a header of a single server gives its CDUs under its serial."""
    return "".join(f"\nCDU: {cdu}" for cdu in getattr(args, "cdus", None) or [])


def duration(seconds: float) -> str:
    """A duration as 1h02m03s, 2m03s or 3s."""
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"


def time_left(step: str, done: int, total: int) -> str:
    """The time left of a step, from the speed of the items done since its first one: the first items
    done by the workers end together, their time would not tell the speed. Empty until it is known."""
    now = time.monotonic()
    first = PROGRESS_STARTS.get(step)
    # A step starting again, for the next context of --auto-traces for instance, starts a new estimate
    if first is None or done <= first[1]:
        PROGRESS_STARTS[step] = (now, done)
        return ""
    started, done_then = first
    if done >= total:
        return ""
    return f", ETA {duration((now - started) / (done - done_then) * (total - done))}"


def progress(step: str, done: int, total: int, unit: str) -> None:
    """Report how far a long step is, after its <done>th item of <total>, with the time left: a bar redrawn
    in place on a terminal, a line every 10 items otherwise, as a journal or a file does not redraw it."""
    if not total:
        return
    eta = time_left(step, done, total)
    if sys.stdout.isatty():
        filled = PROGRESS_WIDTH * done // total
        bar = "#" * filled + "-" * (PROGRESS_WIDTH - filled)
        # The bar is drawn again from the start of the line, cleared, and leaves the cursor there: a
        # message printed meanwhile replaces it instead of following it
        print(f"\r\033[K{step} [{bar}] {done}/{total} {unit}{eta}", end="\n" if done == total else "\r", flush=True)
    elif done % 10 == 0 or done == total:
        print(f"{step}: {done}/{total} {unit}{eta}")


def datapoint(args, serie, sample: int, what: str) -> float:
    """The value of <serie> at <sample>; a missing one is replaced as --ignore-missing-datapoint says: by
    the last known value with 'last', by zero with 'zero' or without the option, which warns about it
    naming <what>."""
    if sample < len(serie):
        return serie[sample]
    option = getattr(args, "ignore_missing_datapoint", "")
    if option == "last" and len(serie):
        return serie[-1]
    if not option:
        print(f"Warning: {what}: Missing sample {sample}, considering 0 watts.")
    return 0


# The characters the mathtext of matplotlib needs escaped
MATHTEXT_SPECIALS = set("_$#%&{} ")


def bold(text: str) -> str:
    """A text drawn in bold in a title, through the mathtext of matplotlib: a title has a single weight."""
    escaped = "".join(f"\\{char}" if char in MATHTEXT_SPECIALS else char for char in text)
    return f"$\\bf{{{escaped}}}$"


def graph_header(args, kind: str, bench_name: str, bench, workers: list[int]) -> str:
    """The header of a graph of several servers: the benchmark and what it runs in bold, and the workers of
    all the servers, [64;640] x stressng for servers of 64 to 640 cores, the ones of the first server
    telling 256 x stressng."""
    count = f"[{workers[0]};{workers[-1]}]" if len(workers) > 1 else None
    return (
        f"{args.title}\n\n{kind} during {bold(bench_name)} benchmark{context_header(args)}{location_header(args)}"
        f"{cdu_header(args)}\n\n{bench.title(count, emphasis=True)}"
    )


def bench_workers(benches) -> list[int]:
    """The numbers of workers of the benchmarks of several servers, which differ with their number of cores."""
    return sorted({workers for bench in benches if (workers := bench.workers()) is not None})
