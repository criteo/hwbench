# AGENTS.md

This file provides guidance to coding agents, like Claude Code, when working with code in this repository.

## What this is

**hwbench** is a benchmark orchestrator that automates low-level testing of servers. It reads an fio-inspired job config, expands it into many individual benchmark runs, tunes/inspects the host, runs external benchmark binaries while collecting environmental metrics (power/thermal/fans via BMC Redfish and PDUs), and writes everything to a `results.json`. **hwgraph** (the `graph/` package) parses that output to plot and compare runs.

Two console entry points (`pyproject.toml`): `hwbench` → `hwbench.hwbench:main`, `hwgraph` → `graph.hwgraph:main`. hwbench must run as **effective uid 0** (system tuning, IPMI, turbostat, fio device access).

## Commands

Tooling is managed with **uv** (>= 0.4.27); Python >= 3.12. `SOURCES = hwbench csv graph tools`.

```bash
make sync_deps        # uv sync --all-extras --dev  (install/refresh env)
make check            # ruff format --diff + ruff check + mypy + pytest  (run before pushing)
make format           # ruff format (apply)
make bundle           # uv build

# Ruff is pinned to RUFF_VERSION in the Makefile and run via `uv tool run ruff@<ver>`.
uv run pytest hwbench graph csv tools    # full test suite
uv run pytest hwbench/bench/test_fio.py  # single file
uv run pytest hwbench/bench/test_fio.py::test_name   # single test
uv run mypy hwbench csv graph tools
```

Run the tools (need root for hwbench):
```bash
uv run hwbench -j configs/curve-cpu.conf -e environment.cfg   # -j jobs config (required), -e environment file (BMC/PDU creds), -t topology file (location by serial), -o out dir, --no-tuning
uv run hwgraph ...    # requires `uv sync --extra graph` (pulls pycairo/matplotlib)
```

## Architecture

The flow in `hwbench/hwbench.py:main()`: parse args → check root → `config.Config(jobs_file)` → `save()` copies it as `job_file.conf` in the out dir → `Benchmarks(out_dir, config)` → check requirements → tune host → dump software + hardware environment → `set_hardware` on both config and benches → `parse_jobs_config()` (expands jobs into benchmarks) → `run()` → `dump()` → write `results.json` (`environment` + `hardware` + `bench` + `config`).

Key subsystems under `hwbench/`:

- **config/** — `Config` wraps a `RawConfigParser` (default section `[global]`). Each job is a section. `parse_range()` implements the fio-style range/group syntax (`4,6`, `0-15`, space-separated groups). `validate_section` dispatches to `validate_<directive>` functions in `config_syntax.py`. `selected_cpus` supports `all`, `none`, CPU lists, `quadrant<x>`/`numa<x>`/`core<x>` resource expansions resolved against the detected CPU topology, and the helpers of `config_helpers.py::HELPERS` (`each-core`, `each-numa`, `each-quadrant`); `REMOVED_HELPERS` (`simple`, `numa-simple`) are rejected with the value to write instead.

- **bench/** — orchestration core.
  - `benchmarks.py` (`Benchmarks`): expands each job into a matrix of `Benchmark` objects. Two scaling axes: **selected_cpus_scaling** (`none` | `iterate` | `plus_N` | `curve`) controls which/how many cores each run is pinned to; **stressor_range_scaling** (`plus_N` | `curve`) iterates stressor counts. Both go through the single `bench/scaling.py::scaling()` function (`SCALINGS` lists the accepted values). `stressor_range=auto` means one stressor per pinned core. Lazily constructs a single `Monitoring` the first time a job needs it (connects BMC + PDUs via Redfish). `run()` executes benchmarks sequentially, optionally `sync_start=time`-aligned; `dump()` writes `expanded_job_file.conf`.
  - `benchmark.py` / `parameters.py` — a single run and its resolved `BenchmarkParameters`.
  - `cpumap.py` — the ASCII CPU map printed by `--dry-run`, or the GPU map for a job loading the GPUs (expansion only: no root, no monitoring connection).
  - `engine.py` — `EngineBase` (one external tool) holds named `EngineModuleBase` modules, and declares in the `resources` class attribute what its benchmarks load (`Resource.CPU`/`GPU`/`DISK`): only a job loading the GPUs expands `selected_gpus`/`selected_gpus_scaling` (same `scaling()`) and requires all-smi. Engines are loaded **dynamically by name**: a `[job]` with `engine=foo` is imported from `hwbench/engines/foo.py` and must expose `Engine()` (see `config.load_engine`). Modules expose parameters; `engine_module_parameter=all` fans out over every module parameter, otherwise an engine can `generate_benchmarks()` to produce a sub-matrix.
  - `monitoring.py` / `monitoring_structs.py` — background-thread polling of turbostat, all-smi (accelerators) + vendor BMC/PDU metrics during a run; the BMC, each PDU and the CDUs are read at the same time, each in its thread.

- **engines/** — concrete engines: `stressng` (+ `stressng_cpu`, `_memrate`, `_stream`, `_qsort`, `_vnni`), `fio`, `pantheon` (accelerators, enumerated by `environment/all_smi.py`), `sleep`, `spike`. All ultimately run external binaries via `utils/external.py::External` (runs with `LC_ALL=C`, captures stdout/stderr to the out dir, calls `parse_cmd`).

- **environment/** — host inspection: `cpu`/`cpu_cores`/`cpu_info`/`numa` (topology used by core-pinning config), `dmi`, `lspci`, `memory`, `block_devices`/`nvme`, `software`, `turbostat`. `hardware.py` (`Hardware`/`BaseHardware`) is the central handle passed everywhere.
  - **environment/vendors/** — `detect.py::first_matching_vendor` tries `Dell`, `Hpe`, `Amd`, then `GenericVendor` (always matches, keep last). A `Vendor` exposes `get_bmc()` (Redfish, generic + OEM endpoints; HPE also `ilorest.py`) and `get_pdus()`. To add a vendor: subclass `Vendor`, implement `detect()`/`prepare()`, register in `VENDOR_LIST`.
  - **CDUs** — `Vendor.get_cdus()` loads `type=CDU` sections with explicit `vendor`, `model` and `protocol`, independently of the server vendor. `environment/vendors/cdus/__init__.py` selects a registered vendor/model driver and rejects unsupported identities. Each model owns its readings, OIDs, units and scales; the initial implementation is HPE MCDU-4U-FR-2 in `cdus/hpe/`. Additional models and vendors register their own drivers without changes to collection, result serialization or graph rendering. The common CDU base owns protocol selection and the request timeout; endpoint syntax, port defaults and credentials belong to protocol drivers. `CDUProtocol` defines the shared `SNMP_V2C`/`SNMP_V3` identifiers; the latter is reserved with no driver implementation. Model profiles explicitly list their supported subset in `SUPPORTED_PROTOCOLS` (HPE MCDU-4U-FR-2: only `SNMP_V2C`), validated before credentials; `SNMPv2cCDU` in `cdus/snmp.py` uses the Python `snmp` package for read-only batched GETs; no Net-SNMP executable is required. Each request owns an engine that is never shared across threads. The refresh period exceeds the timeout to prevent retransmissions. IPv6 endpoint displays use brackets without changing the host sent to the resolver. The read community is required in the configuration’s `community` field and goes directly to the library without subprocesses or temporary files. `bench/cdu_monitoring.py` polls inside the host loop, starting on its first iteration, at the same time as the BMC and each PDU, each in its thread of the pool of `Monitoring`. Every CDU is sampled on every host iteration, with no separate interval setting. SNMP GET responses use the same `cachetools.func.ttl_cache(maxsize=128, ttl=1.5)` protection as Redfish; exceptions are not cached, and cache keys include the driver instance. CDU statistics compact at exactly the same boundaries as host metrics (10 seconds by default). `monitoring.cdus` contains model definitions and per-reading mean/min/max/stdev, sample counts and bounded error counts per window. Empty windows are null, preserving alignment. No individual timestamped readings are stored or supported by hwgraph. Slow CDU requests delay the loop just like BMC/PDU requests, by their own time only. `hardware.cdu` records `type`, `vendor`, `model` and `protocol`. `graph/cdu.py` groups arbitrary model readings by declared unit with generic titles and gaps for nulls. Its legends explicitly summarize equally weighted window means, excluding gaps. `graph/cdu.py` also automatically compares optional primary/secondary supply/return semantic temperature keys with CPU thermal sensors, CPU package power and the selected trace power metric on two axes. Pressure counts remain raw in the initial HPE profile pending unit validation. Community strings never appear in dumps or command arguments.

- **tuning/** — pre-benchmark host tuning (turbo boost, scheduler, power profile, drop_caches) applied by `setup.Tuning`; disabled with `--no-tuning`.

- **utils/** — `external.py` (subprocess base class), `helpers.py` (`h.fatal`, binary checks), `hwlogging.py`, `archive.py`, `dataclasses.py`.

`tools/topology_check.py` validates a topology file (`-t`), the JSON locating the servers of a fleet by serial, against the versioned schema `hwbench/environment/topology-v<N>.schema.json` (`environment/topology.py`; format in `documentation/topology.md`).

`tools/redfish_dump.py` is a script out of the package, like `csv/convert.py`: it records the Redfish urls the BMC driver reads on the target machine, anonymized, as the fixtures of `hwbench/environment/tests/vendors/<vendor>/<model>/` (`sudo uv run tools/redfish_dump.py -e environment.cfg -o <dir>`).

`graph/` is a separate package (`hwgraph.py` entry) that reads result trace files (`trace_filename:logical_name:power_metric` syntax, a `results.json` or a `hwbench-<serial>-<timestamp>.tar.xz` archive) and renders/compares them; it imports shared structs from `hwbench.bench.monitoring_structs`.

## Conventions

- Tests are `test_*.py` colocated with the code they test; many parse fixture command output (`test_parse_*.py`). `environment/mock.py` and `vendors/mock.py` provide mock hardware/vendors for tests.
- New engines and vendors are wired by **name-based dynamic import** / list registration (above) — there is no decorator registry; match the existing module shape exactly.
- Sample job configs live in `configs/*.conf`; renaming one means updating README.md, AGENTS.md and the docs. `documentation/` has `concepts.md`, `configuration.md` (the unique reference of the job file keywords), `cpu-selection.md`, `engines.md`, one page per engine (`stressng.md`, `fio.md`, `pantheon.md`, `spike.md`, `sleep.md`), `monitoring.md`, `topology.md`, `redfish-dump.md`, `hwgraph.md` and its three graph pages (`hwgraph-environment.md`, `hwgraph-scaling.md`, `hwgraph-versus.md`), with the reference dataset of their images in `documentation/example/` (`render.sh` regenerates `documentation/img/`).
- Ruff: line-length 120, `E501`/`ISC001` ignored, `target-version = py39` (so the codebase uses `from __future__ import annotations`). mypy ignores missing imports for the untyped `pyudev` and `snmp` libraries.
- Keywords resolved against the topology (`numa<x>`, `quadrant<x>`, `core<x>`, CPU lists) are machine specific; only `all`, `each-*`, `curve` and `auto` keep their meaning across machines.
- Reuse hwbench's own sources of truth (`HELPERS`, `SCALINGS`, `get_valid_keywords()`, the CPU topology methods…) instead of duplicating a list, a format or some logic.
- CI (`.github/workflows/python-check.yml`) runs `make check_ci bundle` on **every commit**, without stress-ng installed: mock `list_module_parameters` in tests. When the history is rewritten, replay the checks per commit; fix an earlier commit with `git commit --fixup` + autosquash.

## Commits

- Never commit, amend or push without the user's explicit validation, one commit at a time; show the commit message first.
- One fix per commit. The message starts with what goes wrong (the symptom, with the exact error message when there is one), then explains the fix.
- A config or doc commit must not reference pages or keywords that are not committed yet.

`documentation/AGENTS.md` and `configs/AGENTS.md` hold the rules of the pages and of the sample configs.
