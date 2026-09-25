"""Render the expanded benchmarks as an ASCII map of their CPU pinning, one line per benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hwbench.utils import helpers as h

if TYPE_CHECKING:
    from hwbench.environment.cpu import CPU

    from .benchmark import Benchmark
    from .benchmarks import Benchmarks

THREAD_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def legend(glyphs: set[str], threads_per_core: int = 1, cut: bool = False) -> list[str]:
    """Return the map legend, limited to the glyphs the map really uses.

    With SMT, every thread of a core is listed, so the legend explains the second thread
    even when the maps only use the first one.
    """
    entries = []
    if "#" in glyphs:
        entries.append(("#", "all threads of the core are pinned"))
    if threads_per_core > 1:
        for thread in range(1, threads_per_core + 1):
            entries.append((str(thread), f"only its {THREAD_ORDINALS.get(thread, f'{thread}th')} thread is pinned"))
    if "+" in glyphs:
        entries.append(("+", "some of its threads are pinned"))
    if "." in glyphs:
        entries.append((".", "the core is not pinned"))
    if "-" in glyphs:
        entries.append(("-", "the benchmark is not pinned at all"))
    if cut:
        entries.append(("[...]", "benchmarks not pinned on this socket are not shown"))
    width = max([len(glyph) for glyph, _ in entries] + [1])
    return ["map legend: one column per physical core"] + [f"  {glyph:<{width}}  {text}" for glyph, text in entries]


def number_rows(numbers: list[int | None], digits: int) -> list[str]:
    """Return numbers written vertically, one character per column, most significant digit first.

    With 20 NUMA domains, domain 13 is a "1" above a "3": no letter to decode.
    """
    rows = []
    for position in range(digits):
        power = 10 ** (digits - 1 - position)
        rows.append("".join("?" if number is None else str(number // power % 10) for number in numbers))
    return rows


def pinned_cpus(bench: Benchmark) -> list[int]:
    """Return the logical cpus a benchmark is pinned on, empty if it is not pinned."""
    pinned = bench.get_parameters().get_pinned_cpu()
    if pinned == "":
        return []
    if isinstance(pinned, list):
        return sorted(pinned)
    return [int(pinned)]


def cpus_to_str(cpus: list[int]) -> str:
    if not cpus:
        return "no pinning"
    return h.cpu_list_to_range(cpus)


class CpuMap:
    """The physical cores of a CPU, as the columns of the map."""

    def __init__(self, cpu: CPU):
        self.cpu = cpu
        self.sockets = cpu.get_cores_by_socket()
        # (socket, logical cpus of the physical core), one entry per column
        self.columns: list[tuple[int, list[int]]] = [
            (socket, cores) for socket, physical_cores in self.sockets.items() for cores in physical_cores
        ]

    def topology(self) -> str:
        cpu = self.cpu
        return (
            f"{cpu.get_model_name()}: {cpu.get_sockets_count()} socket(s), "
            f"{cpu.get_physical_cores_count()} physical cores, {cpu.get_logical_cores_count()} logical cpus, "
            f"{cpu.get_numa_domains_count()} NUMA domains, {cpu.get_quadrants_count()} quadrants"
        )

    def blocks(self, split_sockets: bool) -> list[list[int]]:
        """Return the column indexes to draw together: all of them, or one block per socket."""
        if not split_sockets:
            return [list(range(len(self.columns)))]
        blocks, start = [], 0
        for physical_cores in self.sockets.values():
            blocks.append(list(range(start, start + len(physical_cores))))
            start += len(physical_cores)
        return blocks

    @staticmethod
    def graduation(block: list[int]) -> tuple[str, str]:
        """Return the core numbers and the ticks of a block, one character per column.

        A tick every 8 cores, numbered from its left, plus a final one on the last core,
        numbered up to it: the map always shows where the CPU ends.
        """
        width = len(block)
        numbers = [" "] * width
        ticks = ["-"] * width
        last = str(block[-1])
        # The last number ends on the last column
        last_start = max(0, width - len(last))
        for position in range(0, width, 8):
            label = str(block[position])
            # Keep a space between a number and the last one, or drop it
            if position == width - 1 or position + len(label) >= last_start:
                continue
            numbers[position : position + len(label)] = label
            ticks[position] = "|"
        numbers[last_start:width] = last[-width:]
        ticks[0] = "|"
        ticks[-1] = "|"
        return "".join(numbers), "".join(ticks)

    def rulers(self, block: list[int], label_width: int, text_header: str) -> list[str]:
        """Return the header lines of a block: core numbers, then the topology of each column."""
        numbers, ticks = self.graduation(block)
        lines = [
            f"{'physical core':<{label_width}}{numbers}  {text_header}",
            f"{'':<{label_width}}{ticks}",
        ]
        if self.cpu.get_sockets_count() > 1:
            lines += self.ruler("socket", block, label_width, lambda socket, _: socket)
        lines += self.ruler("numa domain", block, label_width, lambda _, cores: self.cpu.get_numa_domain(cores[0]))
        if self.cpu.get_quadrants_count() > 1:
            lines += self.ruler("quadrant", block, label_width, lambda _, cores: self.cpu.get_quadrant(cores[0]))
        return lines

    def ruler(self, label: str, block: list[int], label_width: int, value) -> list[str]:
        """Return the lines numbering a topology level for each column, one line per digit."""
        numbers = [value(*column) for column in self.columns]
        # Every block of the machine gets the same number of lines
        digits = len(str(max([number for number in numbers if number is not None] + [0])))
        rows = number_rows([numbers[index] for index in block], digits)
        return [f"{label if row == 0 else '':<{label_width}}{text}" for row, text in enumerate(rows)]

    def line(self, block: list[int], pinned: list[int]) -> str:
        """Return the map of one benchmark over the columns of a block."""
        if not pinned:
            return "-" * len(block)
        pinned_set = set(pinned)
        line = ""
        for index in block:
            threads = [thread for thread, logical_cpu in enumerate(self.columns[index][1]) if logical_cpu in pinned_set]
            if not threads:
                line += "."
            elif len(threads) == len(self.columns[index][1]):
                line += "#"
            elif len(threads) == 1:
                line += str(threads[0] + 1) if threads[0] < 9 else "?"
            else:
                line += "+"
        return line


@dataclass
class Row:
    """What the map shows of one benchmark."""

    job: str
    name: str
    pinned: list[int]
    stressors: int
    engine: str
    skipped: bool

    @classmethod
    def from_benchmark(cls, bench: Benchmark) -> Row:
        params = bench.get_parameters()
        engine_module = bench.get_enginemodule()
        return cls(
            job=params.get_name(),
            name=params.get_name_with_position(),
            pinned=pinned_cpus(bench),
            stressors=params.get_engine_instances_count(),
            engine=engine_module.get_full_name(params.get_engine_module_parameter()),
            skipped=engine_module.fully_skipped_job(params),
        )

    def text(self) -> str:
        """Return the logical cpus column."""
        return cpus_to_str(self.pinned) + (" (skipped)" if self.skipped else "")


# A run of empty lines is cut from this length on: the first and last ones are kept around "[...]"
CUT_EMPTY_LINES = 4


def cut_empty_lines(lines: list[tuple[bool, str]]) -> list[str]:
    """Replace the middle of each long run of empty lines by a "[...]" line."""
    output: list[str] = []
    run: list[str] = []
    for empty, text in [*lines, (False, "")]:
        if empty:
            run.append(text)
            continue
        if len(run) >= CUT_EMPTY_LINES:
            output += [run[0], "[...]", run[-1]]
        else:
            output += run
        run = []
        output.append(text)
    # Drop the sentinel appended to flush the last run
    return output[:-1]


def render(benches: Benchmarks, width: int | None = None) -> str:
    """Return the map of every benchmark, grouped by job, in the order they will run."""
    cpu_map = CpuMap(benches.get_hardware().get_cpu())
    config = benches.get_jobs_config()
    job_config = config.to_dict()
    rows = [Row.from_benchmark(bench) for bench in benches.get_benchmarks()]

    label_width = max([len("physical core")] + [len(row.name) for row in rows]) + 2
    engine_width = max([len("engine/module/parameter")] + [len(row.engine) for row in rows])
    text_header = f"{'stressors':>9}  {'engine/module/parameter':<{engine_width}}  logical cpus"

    # Split the map per socket only when a full line would not fit
    widest_text = max([len(row.text()) for row in rows] + [len("logical cpus")])
    full_width = label_width + len(cpu_map.columns) + 2 + 9 + 2 + engine_width + 2 + widest_text
    split_sockets = width is not None and full_width > width and cpu_map.cpu.get_sockets_count() > 1
    # A line across the map, to see at a glance where a job starts
    blocks = cpu_map.blocks(split_sockets)
    separator_width = full_width - len(cpu_map.columns) + max(len(block) for block in blocks)
    separator_width = min(separator_width, width) if width else separator_width

    output = []
    glyphs: set[str] = set()
    cut = False
    for job in config.get_sections():
        job_rows = [row for row in rows if row.job == job]
        if not job_rows:
            continue
        count = len(job_rows)
        # Fully skipped benchmarks do not run, so they are not part of the job duration
        skipped = len([row for row in job_rows if row.skipped])
        job_runtime = (
            f"{count} benchmark{'s' if count > 1 else ''} x {config.get_runtime(job)}s = "
            f"{h.format_duration(benches.runtime(job))}"
        )
        if skipped:
            job_runtime += f" ({skipped} skipped)"
        output += [
            "",
            f" [{job}] ".center(separator_width, "="),
            # The job as hwbench records it in results.json, with the whole job duration as runtime
            *[
                f"runtime = {job_runtime}" if keyword == "runtime" else f"{keyword}={value}"
                for keyword, value in job_config[job].items()
                if value
            ],
            "",
        ]
        for number, block in enumerate(blocks):
            if number:
                output.append("")
            output += cpu_map.rulers(block, label_width, text_header)
            lines = []
            for row in job_rows:
                line = cpu_map.line(block, row.pinned)
                glyphs.update(line)
                lines.append(
                    (
                        set(line) == {"."},
                        f"{row.name:<{label_width}}{line}  {row.stressors:>9}  {row.engine:<{engine_width}}  {row.text()}",
                    )
                )
            # A socket block of a benchmark pinned elsewhere is empty: only cut them when blocks are split,
            # since an empty line of a whole machine map is a benchmark worth seeing
            block_lines = cut_empty_lines(lines) if split_sockets else [text for _, text in lines]
            cut = cut or "[...]" in block_lines
            output += block_lines
    # The legend comes first, before the run summary, so it is read before the maps
    cpu = cpu_map.cpu
    threads_per_core = cpu.get_logical_cores_count() // cpu.get_physical_cores_count()
    header = [*legend(glyphs, threads_per_core, cut), "", cpu_map.topology(), benches.summary(estimated_end=False)]
    return "\n".join(header + output)
