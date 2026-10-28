from __future__ import annotations

import pathlib
import re
import tarfile
import unicodedata
from dataclasses import dataclass

from graph.common import fatal
from graph.trace import Trace
from hwbench.utils.archive import RESULTS_FILE, archive_output_directory

# The archives create_output_archive() writes next to the output directories
ARCHIVE_PATTERN = "hwbench-*.tar.xz"
# The name of the file of the output directory listing the traces found by --auto-traces
AUTO_TRACES_FILE = "auto_traces.txt"
# The sections of the results.json of hwbench
TRACE_KEYS = ["environment", "hardware", "bench", "config"]
# The characters kept in the name of an output directory, of a context or of a location
CONTEXT_DIRECTORY_CHARACTERS = re.compile(r"[^A-Za-z0-9.-]+")


def ascii_directory_name(text: str) -> str:
    """A text in a directory name: in ASCII, '_' replacing the rest; empty when no character is usable.

    The accents are removed (é gives e), the spaces and the other characters
    replaced by a single '_': 'bios tuning' gives bios_tuning.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return CONTEXT_DIRECTORY_CHARACTERS.sub("_", ascii_text).strip("_.")


def find_trace_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """The results.json and the archives of hwbench under a directory, each run once.

    An archive is written next to the output directory it compresses: the results.json
    of that directory is the same run, so only the archive, the complete one, is kept.
    """
    archives = sorted(directory.rglob(ARCHIVE_PATTERN))
    archived = set()
    for archive in archives:
        try:
            output_directory = archive_output_directory(str(archive))
        except (OSError, tarfile.TarError, EOFError):
            continue
        if output_directory:
            archived.add(archive.parent.resolve() / output_directory)
    results = [path for path in sorted(directory.rglob(RESULTS_FILE)) if path.parent.resolve() not in archived]
    return sorted(archives + results)


def load_traces(directory: pathlib.Path) -> list[Trace]:
    """Load the traces of a directory; a file that is not a trace of hwbench is ignored."""
    if not directory.is_dir():
        fatal(f"{directory} is not a directory")
    traces = []
    for path in find_trace_files(directory):
        try:
            trace = Trace(str(path))
        except (ValueError, OSError, tarfile.TarError, EOFError) as e:
            print(f"auto-traces: ignoring {path}: {e}")
            continue
        # Only hwbench results are traces: a results.json of something else is not
        if not isinstance(trace.get_trace(), dict) or not all(key in trace.get_trace() for key in TRACE_KEYS):
            print(f"auto-traces: ignoring {path}: not a trace of hwbench")
            continue
        # Its header gives its context and its server: its content is read again when rendered
        trace.forget_content()
        traces.append(trace)
    return traces


def list_contexts(directory: pathlib.Path) -> dict[str | None, list[Trace]]:
    """The traces of a directory by context, None gathering the traces without one."""
    contexts: dict[str | None, list[Trace]] = {}
    for trace in load_traces(directory):
        contexts.setdefault(trace.get_context(), []).append(trace)
    return contexts


def print_contexts(directory: pathlib.Path) -> None:
    """Print the contexts of the traces of a directory, with their traces."""
    contexts = list_contexts(directory)
    named = sorted(context for context in contexts if context is not None)
    print(f"Contexts found in {directory}:")
    if not named:
        print("none")
    for context in named:
        traces = contexts[context]
        print(f"{context}: {len(traces)} trace{'s' if len(traces) > 1 else ''}")
        for trace in traces:
            print(f"  {trace.server_name()}  {trace.get_filename()}")
    if None in contexts:
        print(f"{len(contexts[None])} trace{'s' if len(contexts[None]) > 1 else ''} without context")


@dataclass
class AutoTraces:
    """The traces of a context found in a directory by --auto-traces."""

    directory: pathlib.Path
    context: str
    traces: list[Trace]

    def description(self) -> list[str]:
        """The traces used, one line each: their logical name and their file."""
        lines = [f"Traces of the context '{self.context}' found in {self.directory}:"]
        width = max(len(trace.get_name()) for trace in self.traces)
        lines += [f"{trace.get_name().ljust(width)}  {trace.get_filename()}" for trace in self.traces]
        return lines

    def output_directory_name(self) -> str:
        """The subdirectory of --outdir rendering the context: its name in ASCII, see ascii_directory_name()."""
        name = ascii_directory_name(self.context)
        if not name:
            fatal(f"the context '{self.context}' has no character usable in a directory name")
        return name


def parse_auto_traces(value: str) -> tuple[pathlib.Path, str | None, str]:
    """Split <directory>:<context>:<power_metric>: the context runs from the first to the last ':'.

    An empty context, <directory>::<power_metric>, gives None: every context of the directory.
    """
    directory, separator, rest = value.partition(":")
    context, separator2, power_metric = rest.rpartition(":")
    if not separator or not separator2 or not directory or not power_metric:
        # A context holding a space, not quoted, is split by the shell before the power metric
        hint = ", quote it when the context holds a space" if not separator2 else ""
        fatal(f"{value} does not match 'directory:context:power_metric' syntax{hint}")
    return pathlib.Path(directory), context or None, power_metric


def context_traces(directory: pathlib.Path, context: str, traces: list[Trace], power_metric: str) -> AutoTraces:
    """The traces of a context, named after their server.

    Each server must appear once: the same serial found several times with the same
    context makes the traces ambiguous, and stops hwgraph with the files involved.
    """
    by_server: dict[str | None, list[Trace]] = {}
    for trace in traces:
        by_server.setdefault(trace.server_name(), []).append(trace)
    for server, server_traces in sorted(by_server.items(), key=lambda item: str(item[0])):
        if len(server_traces) > 1:
            files = ", ".join(trace.get_filename() for trace in server_traces)
            fatal(f"{server} is found {len(server_traces)} times with the context '{context}': {files}")

    for trace in traces:
        # No logical name: the trace is named after its server, as with <file>::<power_metric>
        trace.metric_name = power_metric
        # Validated when rendered, one trace at a time, from the cache of the output directory
        trace.set_logical_name()
    return AutoTraces(directory, context, sorted(traces, key=lambda trace: trace.get_name()))


def find_auto_traces(value: str) -> list[AutoTraces]:
    """The traces of <directory>:<context>:<power_metric>, one AutoTraces per context rendered.

    Without context, every context of the directory is rendered, each in its own
    subdirectory: two contexts giving the same subdirectory stop hwgraph.
    """
    directory, context, power_metric = parse_auto_traces(value)
    contexts = list_contexts(directory)
    named = sorted(c for c in contexts if c is not None)
    if context is None:
        if not named:
            fatal(f"no trace with a context in {directory}")
        if None in contexts:
            print(f"auto-traces: {len(contexts[None])} trace(s) without context in {directory} are not rendered")
        selected = [context_traces(directory, name, contexts[name], power_metric) for name in named]
        by_directory: dict[str, list[str]] = {}
        for auto in selected:
            by_directory.setdefault(auto.output_directory_name(), []).append(auto.context)
        for name, same in by_directory.items():
            if len(same) > 1:
                fatal(f"the contexts {', '.join(repr(c) for c in same)} are all rendered in the directory {name}")
        return selected

    if context not in contexts:
        found = ", ".join(f"'{name}'" for name in named) or "none"
        fatal(f"no trace with the context '{context}' in {directory}, contexts found: {found}")
    return [context_traces(directory, context, contexts[context], power_metric)]
