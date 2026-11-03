from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

# The file of the output directory listing what the graphs printed, job by job
RENDERING_LOG = "rendering.log"
# The start of the lines reporting an error or a warning; the lines of a traceback follow their error
ERROR_PREFIXES = ("Error", "Fatal", "An error")
WARNING_PREFIXES = ("Warning",)


def level(line: str) -> str | None:
    """'error' or 'warning' for a line reporting one, None for the other lines."""
    if line.startswith(ERROR_PREFIXES):
        return "error"
    if line.startswith(WARNING_PREFIXES):
        return "warning"
    return None


@dataclass
class RenderLog:
    """What the tasks of a rendering printed, by job then by graph, with the number of errors and warnings."""

    # job -> graph -> lines; the tasks of no job, like the comparison reports, have an empty job
    entries: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    errors: int = 0
    warnings: int = 0

    def add(self, job: str, graph: str, output: str) -> None:
        """Keep what a task rendering <graph> of <job> printed."""
        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            return
        self.entries.setdefault(job, {}).setdefault(graph, []).extend(lines)
        for line in lines:
            found = level(line)
            self.errors += found == "error"
            self.warnings += found == "warning"

    def summary(self) -> str:
        return f"{self.errors} error{'s' * (self.errors != 1)}, {self.warnings} warning{'s' * (self.warnings != 1)}"

    def write(self, output_dir: pathlib.Path) -> pathlib.Path | None:
        """Write the log in output_dir, None when the tasks printed nothing; a log of an earlier rendering
        in the same directory is removed."""
        log_file = output_dir.joinpath(RENDERING_LOG)
        log_file.unlink(missing_ok=True)
        if not self.entries:
            return None
        lines = [f"hwgraph rendering of {output_dir}: {self.summary()}"]
        for job in sorted(self.entries):
            lines += ["", f"== {job or 'all the jobs'}"]
            for graph in sorted(self.entries[job]):
                lines += [f"-- {graph}", *(f"   {line}" for line in self.entries[job][graph])]
        log_file.write_text("\n".join(lines) + "\n")
        return log_file
