# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**hwbench** is a benchmark orchestrator that automates low-level testing of servers. It reads an fio-inspired job config, expands it into many individual benchmark runs, tunes/inspects the host, runs external benchmark binaries while collecting environmental metrics (power/thermal/fans via BMC Redfish and PDUs), and writes everything to a `results.json`. **hwgraph** (the `graph/` package) parses that output to plot and compare runs.

Two console entry points (`pyproject.toml`): `hwbench` → `hwbench.hwbench:main`, `hwgraph` → `graph.hwgraph:main`. hwbench must run as **effective uid 0** (system tuning, IPMI, turbostat, fio device access).

## Commands

Tooling is managed with **uv** (>= 0.4.27); Python >= 3.12. `SOURCES = hwbench csv graph`.

```bash
make sync_deps        # uv sync --all-extras --dev  (install/refresh env)
make check            # ruff format --diff + ruff check + mypy + pytest  (run before pushing)
make format           # ruff format (apply)
make bundle           # uv build

# Ruff is pinned to RUFF_VERSION in the Makefile and run via `uv tool run ruff@<ver>`.
uv run pytest hwbench graph csv          # full test suite
uv run pytest hwbench/bench/test_fio.py  # single file
uv run pytest hwbench/bench/test_fio.py::test_name   # single test
uv run mypy hwbench csv graph
```

Run the tools (need root for hwbench):
```bash
uv run hwbench -j configs/curve-cpu.conf -m monitoring.cfg   # -j jobs config (required), -m monitoring creds, -o out dir, --no-tuning
uv run hwgraph ...    # requires `uv sync --extra graph` (pulls pycairo/matplotlib)
```

## Architecture

The flow in `hwbench/hwbench.py:main()`: parse args → check root → `config.Config(jobs_file)` → `Benchmarks(out_dir, config)` → check requirements → tune host → dump software + hardware environment → `set_hardware` on both config and benches → `parse_jobs_config()` (expands jobs into benchmarks) → `run()` → `dump()` → write `results.json` (`environment` + `hardware` + `bench` + `config`).

Key subsystems under `hwbench/`:

- **config/** — `Config` wraps a `RawConfigParser` (default section `[global]`). Each job is a section. `parse_range()` implements the fio-style range/group syntax (`4,6`, `0-15`, space-separated groups). `validate_section` dispatches to `validate_<directive>` functions in `config_syntax.py`. `selected_cpus` supports `all`, `none`, CPU lists, `quadrant<x>`/`numa<x>`/`core<x>` resource expansions resolved against the detected CPU topology, and the helpers of `config_helpers.py::HELPERS` (`each-core`, `each-numa`, `each-quadrant`); `REMOVED_HELPERS` (`simple`, `numa-simple`) are rejected with the value to write instead.

- **bench/** — orchestration core.
  - `benchmarks.py` (`Benchmarks`): expands each job into a matrix of `Benchmark` objects. Two scaling axes: **selected_cpus_scaling** (`none` | `iterate` | `plus_N` | `curve`) controls which/how many cores each run is pinned to; **stressor_range_scaling** (`plus_N` | `curve`) iterates stressor counts. Both go through the single `bench/scaling.py::scaling()` function (`SCALINGS` lists the accepted values). `stressor_range=auto` means one stressor per pinned core. Lazily constructs a single `Monitoring` the first time a job needs it (connects BMC + PDUs via Redfish). `run()` executes benchmarks sequentially, optionally `sync_start=time`-aligned; `dump()` writes `expanded_job_file.conf`.
  - `benchmark.py` / `parameters.py` — a single run and its resolved `BenchmarkParameters`.
  - `cpumap.py` — the ASCII CPU map printed by `--dry-run` (expansion only: no root, no monitoring connection).
  - `engine.py` — `EngineBase` (one external tool) holds named `EngineModuleBase` modules. Engines are loaded **dynamically by name**: a `[job]` with `engine=foo` is imported from `hwbench/engines/foo.py` and must expose `Engine()` (see `config.load_engine`). Modules expose parameters; `engine_module_parameter=all` fans out over every module parameter, otherwise an engine can `generate_benchmarks()` to produce a sub-matrix.
  - `monitoring.py` / `monitoring_structs.py` — background-thread polling of turbostat + vendor BMC/PDU metrics during a run.

- **engines/** — concrete engines: `stressng` (+ `stressng_cpu`, `_memrate`, `_stream`, `_qsort`, `_vnni`), `fio`, `sleep`, `spike`. All ultimately run external binaries via `utils/external.py::External` (runs with `LC_ALL=C`, captures stdout/stderr to the out dir, calls `parse_cmd`).

- **environment/** — host inspection: `cpu`/`cpu_cores`/`cpu_info`/`numa` (topology used by core-pinning config), `dmi`, `lspci`, `memory`, `block_devices`/`nvme`, `software`, `turbostat`. `hardware.py` (`Hardware`/`BaseHardware`) is the central handle passed everywhere.
  - **environment/vendors/** — `detect.py::first_matching_vendor` tries `Dell`, `Hpe`, `Amd`, then `GenericVendor` (always matches, keep last). A `Vendor` exposes `get_bmc()` (Redfish, generic + OEM endpoints; HPE also `ilorest.py`) and `get_pdus()`. To add a vendor: subclass `Vendor`, implement `detect()`/`prepare()`, register in `VENDOR_LIST`.

- **tuning/** — pre-benchmark host tuning (turbo boost, scheduler, power profile, drop_caches) applied by `setup.Tuning`; disabled with `--no-tuning`.

- **utils/** — `external.py` (subprocess base class), `helpers.py` (`h.fatal`, binary checks), `hwlogging.py`, `archive.py`, `dataclasses.py`.

`graph/` is a separate package (`hwgraph.py` entry) that reads result trace files (`filename:logical_name:power_metric` syntax) and renders/compares them; it imports shared structs from `hwbench.bench.monitoring_structs`.

## Conventions

- Tests are `test_*.py` colocated with the code they test; many parse fixture command output (`test_parse_*.py`). `environment/mock.py` and `vendors/mock.py` provide mock hardware/vendors for tests.
- New engines and vendors are wired by **name-based dynamic import** / list registration (above) — there is no decorator registry; match the existing module shape exactly.
- Sample job configs live in `configs/*.conf`. `documentation/` has `concepts.md`, `configuration.md` (the unique reference of the job file keywords), `cpu-selection.md`, `engines.md`, one page per engine (`stressng.md`, `fio.md`, `spike.md`, `sleep.md`) and `monitoring.md`.
- Ruff: line-length 120, `E501`/`ISC001` ignored, `target-version = py39` (so the codebase uses `from __future__ import annotations`). mypy ignores missing imports for `pyudev`.
</content>
</invoke>
- Reuse hwbench's own sources of truth (`HELPERS`, `SCALINGS`, `get_valid_keywords()`, the CPU topology methods…) instead of duplicating a list, a format or some logic.
- CI (`.github/workflows/python-check.yml`) runs `make check_ci bundle` on **every commit**, without stress-ng installed: mock `list_module_parameters` in tests. When the history is rewritten, replay the checks per commit; fix an earlier commit with `git commit --fixup` + autosquash.

## Commits

- Never commit, amend or push without the user's explicit validation, one commit at a time; show the commit message first.
- One fix per commit. The message starts with what goes wrong (the symptom, with the exact error message when there is one), then explains the fix.
- A config or doc commit must not reference pages or keywords that are not committed yet.

## Documentation style

- English. The documentation is **generic**: say "the target machine", never "that machine" or "the machine"; the only named machine is the example CPU of `cpu-selection.md` (AMD EPYC 8534P, 64 cores, 8 NUMA domains, 4 quadrants, NPS4 with LLC as NUMA).
- Every statement is checked against the code: exact keyword values, exact error messages, exact output formats (e.g. the benchmark start line). Describe the real behavior, even when it is a bug to fix later.
- Page layout: title `# Name: subtitle` (e.g. `# fio: storage benchmarking`), a short intro, a TOC of the `#` sections, a `Related pages:` line, then the sections, ending with `# Implementation notes` (files, classes, methods) when useful.
- Tables:
  - the values of an option: `| Value | Effect |`;
  - keys: `| Key | Value | Effect |`.
- Callouts:
  ```
  > ℹ️ **Info**
  >
  > text
  ```
  and `> 💡 **Good practice**` with the same shape.
- Commands are written `uv run hwbench …`; job file snippets use an ```` ```ini ```` fence.
- Headings of keywords are lowercase, as the keyword (`### outlet`), so the anchors match; check every `#anchor` link after renaming a heading.
- `configuration.md` is the unique reference of the job file keywords: the other pages link to it rather than repeating it.
- Topology vocabulary: NPS sets how the memory controllers (DDR) are associated to the cores, which gives the **quadrants**; LLC as NUMA exposes each L3 cache as a **NUMA domain**. What `numa<x>` covers therefore depends on the BIOS settings and cannot be known in advance by a job file.
- Keywords resolved against the topology (`numa<x>`, `quadrant<x>`, `core<x>`, CPU lists) are machine specific; only `all`, `each-*`, `curve` and `auto` keep their meaning across machines.

## Sample configs (`configs/*.conf`)

- The file starts with `# Intention: <what the file measures>`.
- Each job has `# engine <name>: see documentation/<engine>.md#<section>` above `engine=`.
- A contextualized comment above each `selected_cpus`, `*_scaling` and `stressor_*` line says what it does in this job, with a link to the exact section: `# <what it does here>: see documentation/<page>.md#<section>`.
- Do not write directives that only repeat their default value.
- The name says what the file does (`curve-cpu.conf`, `curve-numa.conf`); update README.md, CLAUDE.md and the docs when renaming one.
