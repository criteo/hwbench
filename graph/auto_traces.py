from __future__ import annotations

import json
import pathlib
import re
import tarfile
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from graph.common import DEFAULT_JOBS, fatal, progress
from graph.trace import Trace
from hwbench.utils.archive import RESULTS_FILE, read_results_of_archive

# The archives of create_output_archive(), whatever their name: the ones holding a results.json
ARCHIVE_PATTERN = "*.tar.xz"
# The name of the file of the output directory listing the traces found by --auto-traces
AUTO_TRACES_FILE = "auto_traces.txt"
# The sections of the results.json of hwbench
TRACE_KEYS = ["environment", "hardware", "bench", "config"]
# The characters kept in the name of an output directory, of a context or of a location
CONTEXT_DIRECTORY_CHARACTERS = re.compile(r"[^A-Za-z0-9.-]+")
# The subdirectory of --outdir rendering the traces without context
NO_CONTEXT_DIRECTORY = "no_context"


def ascii_directory_name(text: str) -> str:
    """A text in a directory name: in ASCII, '_' replacing the rest; empty when no character is usable.

    The accents are removed (é gives e), the spaces and the other characters
    replaced by a single '_': 'bios tuning' gives bios_tuning.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return CONTEXT_DIRECTORY_CHARACTERS.sub("_", ascii_text).strip("_.")


def read_trace_file(path: pathlib.Path) -> tuple[str | None, dict | None, str | None]:
    """Read a results.json or an archive, in a worker: the output directory an archive holds, the header
    of the trace, without its benchmarks, and why the file is ignored. A .tar.xz without results.json
    is not a trace: it gives neither header nor reason."""
    output_directory = None
    try:
        if path.name == RESULTS_FILE:
            content = path.read_bytes()
        else:
            found = read_results_of_archive(str(path))
            if found is None:
                return None, None, None
            output_directory, content = found
    except (OSError, tarfile.TarError, EOFError) as e:
        return None, None, f"not a readable archive: {e}" if path.name != RESULTS_FILE else str(e)
    try:
        trace = json.loads(content)
    except ValueError:
        return output_directory, None, f"{path} is not a valid JSON file"
    # Only hwbench results are traces: a results.json of something else is not
    if not isinstance(trace, dict) or not all(key in trace for key in TRACE_KEYS):
        return output_directory, None, "not a trace of hwbench"
    return output_directory, {key: value for key, value in trace.items() if key != "bench"}, None


def read_trace_files(directory: pathlib.Path, jobs: int = DEFAULT_JOBS) -> list[tuple[pathlib.Path, dict]]:
    """The header of each trace of hwbench under a directory, each run once, read by <jobs> workers.

    An archive is written next to the output directory it compresses: the results.json
    of that directory is the same run, so only the archive, the complete one, is kept.
    """
    if not directory.is_dir():
        fatal(f"{directory} is not a directory")
    # Finding then reading the traces of a fleet takes a while: say so, then how far it is
    print(f"auto-traces: looking for the traces in {directory}")
    # Whatever its name, once renamed by the tool collecting it: an archive holding a results.json
    paths = sorted(directory.rglob(ARCHIVE_PATTERN)) + sorted(directory.rglob(RESULTS_FILE))
    print(f"auto-traces: reading the {len(paths)} files found")
    read: dict[pathlib.Path, tuple[str | None, dict | None, str | None]] = {}
    with ProcessPoolExecutor(max_workers=max(1, min(jobs, len(paths)))) as pool:
        for index, (path, result) in enumerate(zip(paths, pool.map(read_trace_file, paths, chunksize=4)), 1):
            read[path] = result
            progress("auto-traces", index, len(paths), "files read")
    archived = {path.parent.resolve() / output for path, (output, _, _) in read.items() if output}
    traces = []
    for path in sorted(read):
        _, header, problem = read[path]
        if path.name == RESULTS_FILE and path.parent.resolve() in archived:
            continue
        if problem:
            print(f"auto-traces: ignoring {path}: {problem}")
        elif header is not None:
            traces.append((path, header))
    return traces


def load_traces(directory: pathlib.Path, jobs: int = DEFAULT_JOBS) -> list[Trace]:
    """Load the traces of a directory, without their content; a file that is not a trace of hwbench is
    ignored."""
    traces = []
    for path, header in read_trace_files(directory, jobs):
        trace = Trace(str(path), load=False)
        # Its header gives its context and its server: its content is read again when rendered
        trace.load_header(header)
        traces.append(trace)
    return traces


def list_contexts(directory: pathlib.Path, jobs: int = DEFAULT_JOBS) -> dict[str | None, list[Trace]]:
    """The traces of a directory by context, None gathering the traces without one."""
    contexts: dict[str | None, list[Trace]] = {}
    for trace in load_traces(directory, jobs):
        contexts.setdefault(trace.get_context(), []).append(trace)
    return contexts


def print_contexts(directory: pathlib.Path, jobs: int = DEFAULT_JOBS) -> None:
    """Print the contexts of the traces of a directory, with their traces."""
    contexts = list_contexts(directory, jobs)
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
    """The traces of a context found in a directory by --auto-traces, context None for the traces without one."""

    directory: pathlib.Path
    context: str | None
    traces: list[Trace]

    def label(self) -> str:
        """The context in a sentence: "with the context '<context>'", or "without context"."""
        return f"with the context '{self.context}'" if self.context is not None else "without context"

    def description(self) -> list[str]:
        """The traces used, one line each: their logical name and their file."""
        lines = [f"Traces {self.label()} found in {self.directory}:"]
        width = max(len(trace.get_name()) for trace in self.traces)
        lines += [f"{trace.get_name().ljust(width)}  {trace.get_filename()}" for trace in self.traces]
        return lines

    def output_directory_name(self) -> str:
        """The subdirectory of --outdir rendering the context: its name in ASCII, see ascii_directory_name(),
        NO_CONTEXT_DIRECTORY for the traces without context."""
        if self.context is None:
            return NO_CONTEXT_DIRECTORY
        name = ascii_directory_name(self.context)
        if not name:
            fatal(f"the context '{self.context}' has no character usable in a directory name")
        return name


def parse_auto_traces(value: str) -> tuple[pathlib.Path, str | None, str]:
    """Split <directory>:<context>:<power_metric>: the context runs from the first to the last ':'.

    An empty context, <directory>::<power_metric>, gives None: every context of the directory,
    and the traces without context.
    """
    directory, separator, rest = value.partition(":")
    context, separator2, power_metric = rest.rpartition(":")
    if not separator or not separator2 or not directory or not power_metric:
        # A context holding a space, not quoted, is split by the shell before the power metric
        hint = ", quote it when the context holds a space" if not separator2 else ""
        fatal(f"{value} does not match 'directory:context:power_metric' syntax{hint}")
    return pathlib.Path(directory), context or None, power_metric


def context_traces(directory: pathlib.Path, context: str | None, traces: list[Trace], power_metric: str) -> AutoTraces:
    """The traces of a context, or without context when None, named after their server.

    Each server must appear once: the same serial found several times with the same
    context makes the traces ambiguous, and stops hwgraph with the files involved.
    """
    auto = AutoTraces(directory, context, traces)
    by_server: dict[str | None, list[Trace]] = {}
    for trace in traces:
        by_server.setdefault(trace.server_name(), []).append(trace)
    for server, server_traces in sorted(by_server.items(), key=lambda item: str(item[0])):
        if len(server_traces) > 1:
            files = ", ".join(trace.get_filename() for trace in server_traces)
            fatal(f"{server} is found {len(server_traces)} times {auto.label()}: {files}")

    for trace in traces:
        # No logical name: the trace is named after its server, as with <file>::<power_metric>
        trace.metric_name = power_metric
        # Validated when rendered, one trace at a time, from the cache of the output directory
        trace.set_logical_name()
    auto.traces = sorted(traces, key=lambda trace: trace.get_name())
    return auto


def find_auto_traces(value: str, jobs: int = DEFAULT_JOBS) -> list[AutoTraces]:
    """The traces of <directory>:<context>:<power_metric>, one AutoTraces per context rendered.

    Without context, every context of the directory is rendered, each in its own
    subdirectory, then the traces without context, together in NO_CONTEXT_DIRECTORY:
    two contexts giving the same subdirectory stop hwgraph.
    """
    directory, context, power_metric = parse_auto_traces(value)
    contexts = list_contexts(directory, jobs)
    named = sorted(c for c in contexts if c is not None)
    if context is None:
        if not contexts:
            fatal(f"no trace in {directory}")
        selected = [context_traces(directory, name, contexts[name], power_metric) for name in named]
        if None in contexts:
            selected.append(context_traces(directory, None, contexts[None], power_metric))
        by_directory: dict[str, list[str]] = {}
        for auto in selected:
            by_directory.setdefault(auto.output_directory_name(), []).append(
                repr(auto.context) if auto.context is not None else "the traces without context"
            )
        for name, same in by_directory.items():
            if len(same) > 1:
                fatal(f"the contexts {', '.join(same)} are all rendered in the directory {name}")
        return selected

    if context not in contexts:
        found = ", ".join(f"'{name}'" for name in named) or "none"
        fatal(f"no trace with the context '{context}' in {directory}, contexts found: {found}")
    return [context_traces(directory, context, contexts[context], power_metric)]
