# Configuration file reference

hwbench is driven by a single *job file*, passed with `-j`. This page describes its
format and every keyword it accepts.

- [File format](#file-format)
- [Keyword summary](#keyword-summary)
- [Keyword reference](#keyword-reference)
- [Legacy and unimplemented keywords](#legacy-and-unimplemented-keywords)
- [Startup validation](#startup-validation)
- [Implementation notes](#implementation-notes)

Related pages: [concepts.md](concepts.md) (job vs benchmark, the vocabulary used
everywhere), [cpu-selection.md](cpu-selection.md) (CPU pinning, and how a job becomes
many benchmarks), and one page per engine:
[stressng.md](stressng.md), [fio.md](fio.md), [spike.md](spike.md), [sleep.md](sleep.md).

# File format

```ini
[global]
runtime=120
monitor=all
engine=stressng
selected_cpus=all
selected_cpus_scaling=none
stressor_range=auto

[check_integer_perf]
engine_module=cpu
engine_module_parameter=int8,int64,int128

[check_memory_bandwidth_perf]
engine_module=stream
```

Two jobs, both loading the whole machine for 120 seconds with monitoring enabled: three
benchmarks for `check_integer_perf`, one per parameter, and one for
`check_memory_bandwidth_perf`.

- Every section except `[global]` defines one **job**, named after the section.
- `[global]` provides the default value of any keyword; a job redefining a keyword
  overrides it for itself only.

Putting everything the jobs have in common in `[global]` is good practice: in the
example above, only what actually differs between the two jobs — the engine module and
its parameters — is written in the job sections. The file stays short, each job reads in
two lines, and a change of duration or of CPU selection applies to the whole file at
once. It also makes the intention of each job obvious, since nothing distracts from what
makes it specific.

This is one of hwbench's strengths: a short file can represent hundreds of tests running
for hours. `configs/curve-cpu.conf` is 17 lines of keywords and 6 jobs; on the AMD EPYC 8534P, a 64-core CPU, it
instantiates into 91 benchmarks and about three hours of benchmarking. You keep
writing [intentions](concepts.md#a-job-is-an-intention), and the complexity of
instantiating them on a large machine stays where it belongs — in hwbench, not in your
file.

Other rules of the format:

- `#` and `;` start a comment, on their own line only: inline comments are not enabled,
  so `runtime=10 ; seconds` sets the value to `10 ; seconds` and fails validation.
- `key=value` and `key: value` are both accepted; the exact syntax is the one of Python's
  `configparser`, specified in
  [Supported INI File Structure](https://docs.python.org/3/library/configparser.html#supported-ini-file-structure).
- Write the values in **lowercase**: they are validated as written, then lowercased when
  read, so `monitor=ALL` is rejected. Engine specific keywords, like the device paths of
  [`disks`](#disks), are kept as written.
- A keyword can only appear once per section.

# Keyword summary

| Keyword | What it decides | Values | Default |
|---|---|---|---|
| [`runtime`](#runtime) | how long each benchmark runs | integer (seconds) | `60` |
| [`monitor`](#monitor) | whether the environment is observed during the job | `none`, `all` | `none` |
| [`engine`](#engine) | which benchmark logic runs | `stressng`, `fio`, `spike`, `sleep` | **mandatory** |
| [`engine_module`](#engine_module) | which testing mode on that engine | depends on the engine | the engine name |
| [`engine_module_parameter`](#engine_module_parameter) | what is handed to that mode | depends on the module, or `all` | the module name |
| [`engine_module_parameter_base`](#engine_module_parameter_base) | a static string handed to that mode | free text, engine specific | empty |
| [`selected_cpus`](#selected_cpus) | which CPUs will be used for the job, hence the pinning | cpu list, `core<x>`, `numa<x>`, `quadrant<x>`, `each-core`, `each-numa`, `each-quadrant`, `all`, `none` | `none` |
| [`selected_cpus_scaling`](#selected_cpus_scaling) | the iteration method over the CPUs that will be used | `iterate`, `none`, `plus_<x>`, `curve` | `iterate` |
| [`stressor_range`](#stressor_range) | how the stressor count evolves in the CPU group of each iteration | integer, range, list, `auto` | `1` |
| [`stressor_range_scaling`](#stressor_range_scaling) | how those stressor counts become benchmarks | `plus_<x>`, `curve` | `plus_1` |
| [`skip_method`](#skip_method) | what happens when a benchmark must be skipped | `bypass`, `wait` | `bypass` |
| [`sync_start`](#sync_start) | when a benchmark is allowed to start | `none`, `time` | `none` |
| `thermal_start`, `fans_start` | planned: gate the job on the chassis state | accepted, [ignored](#accepted-but-not-implemented) | — |

Engines may add their own keywords, listed in [Engine specific keywords](#engine-specific-keywords):
today only [`disks`](#disks), mandatory for `fio`. Any other keyword is rejected at startup.

# Keyword reference

## runtime

Duration in seconds of **each** benchmark, not of the job: a job expanded into 64
benchmarks with `runtime=120` runs for 64 × 120 seconds.

| Value | Effect |
|---|---|
| `<seconds>` | the duration of each benchmark, an integer (default `60`) |

## monitor

Collects environmental metrics (power, thermal, fans, frequencies) during each benchmark
of the job. Requires the `-m` option, see [monitoring.md](monitoring.md).

| Value | Effect |
|---|---|
| `none` | no monitoring (default) |
| `all` | collect everything the server exposes |

Only these two values are supported today; anything else is rejected at startup. The
keyword is a text one on purpose: the intent is to make monitoring **modular**, letting
a job select the sources or metric families it needs (thermal, power, fans, …) instead
of the current all-or-nothing switch.

## engine

The engine implementing the benchmark logic, either as a wrapper around an external tool
or as hwbench's own code. Mandatory: a job without a valid engine is fatal.

| Value | Effect |
|---|---|
| `stressng` | CPU and memory micro-benchmarks, see [stressng.md](stressng.md) |
| `fio` | storage benchmarking, see [fio.md](fio.md) |
| `spike` | applies load spikes to study the cooling: fan algorithm, fan speed, power, see [spike.md](spike.md) |
| `sleep` | applies no load: a pause between jobs, or an idle environment reference, see [sleep.md](sleep.md) |

The binary an engine needs is checked before the run starts, so a missing tool is
reported early. See [engines.md](engines.md) for the model itself.

## engine_module

One testing mode on that engine. Defaults to the **engine name**, which is why
`engine=sleep` needs nothing else.

| Value | Effect |
|---|---|
| `cpu`, `qsort`, `stream`, `memrate`, `vnni` | the modules of `engine=stressng`, see [stressng.md](stressng.md) |
| `cmdline` | the module of `engine=fio`, see [fio.md](fio.md) |
| `cpu` | the module of `engine=spike`, see [spike.md](spike.md) |
| `sleep` | the module of `engine=sleep`, see [sleep.md](sleep.md) |

What each module does, and what it expects, is documented on the engine's own page: the
list above is only a map.

## engine_module_parameter

A parameter handed to the engine module. What it means is defined by the engine, so the
values it accepts are documented on the engine's own page. A list is accepted and **each
item creates its own benchmark**.

```ini
[check_integer_perf]
engine_module=cpu
engine_module_parameter=int8,int64,int128
```

The accepted values depend on the module, and for some modules on the target machine itself:

| Value | Effect |
|---|---|
| `int8`, `int64`, `int128`, `fft`, `matrixprod`, … | with `stressng` / `cpu`: a method listed by `stress-ng --cpu-method list` on the target machine |
| `noavx_vpaddb`, `noavx_vpdpbusd`, `noavx_vpdpwssd` | with `stressng` / `vnni`: runs on any CPU |
| `avx_vpaddb512` | with `stressng` / `vnni`: needs the `avx512bw` CPU flag |
| `avx_vpdpbusd512`, `avx_vpdpwssd512` | with `stressng` / `vnni`: needs the `avx512_vnni` CPU flag |
| `avx_vpaddb128`, `avx_vpaddb256`, `avx_vpdpbusd128`, `avx_vpdpbusd256`, `avx_vpdpwssd128`, `avx_vpdpwssd256` | with `stressng` / `vnni`: needs the `avx_vnni` CPU flag |
| the module name | the only value of `stressng` / `qsort`, `stream`, `memrate`, `fio` / `cmdline` — the test itself being in `engine_module_parameter_base` — `spike` / `cpu` and `sleep` / `sleep`; the default of every module |
| `all` | every parameter the module exposes on the target machine |
| `<a>,<b>,<c>` | a list of the values above, each item creating its own benchmark |

Items are validated at startup against what the module really exposes, so a typo fails
in seconds instead of hours.

The `vnni` modes depend on the capabilities of the processor: a mode needing an
instruction set the CPU does not have — the `avx512bw`, `avx512_vnni` or `avx_vnni` flag
listed above — is not available on the target machine. The job file stays valid, so the same
file can run on any server: the benchmark is skipped, reported with empty values, and
[`skip_method`](#skip_method) decides whether its time is given back (`bypass`) or spent
idle (`wait`). A dry run marks a bypassed benchmark `(skipped)`.

What each module does is documented on the engine's own page:
[stressng.md](stressng.md), [fio.md](fio.md), [spike.md](spike.md),
[sleep.md](sleep.md).

## engine_module_parameter_base

A static string handed to the engine module, for engines needing a command line or a
custom syntax, shared by every benchmark of the job. It is only interpreted by the
implementation of some engines in hwbench:

| Value | Effect |
|---|---|
| fio options, like `--direct=1 --rw=randread --bs=4k` | with `engine=fio`: the fio options of the test, the disks being given by [`disks`](#disks) |
| `high:<seconds> low:<seconds>`, `auto:<percent>`, like `high:10 low:5` | with `engine=spike`: seconds loaded and idle per cycle, and the fan speed change to detect |
| empty (default) | not read by `stressng` and `sleep` |

The details of each syntax are on the engine's page: [fio.md](fio.md),
[spike.md](spike.md).

## selected_cpus

Which logical CPUs will be used for the benchmarks of this job, hence the pinning.

| Value | Effect |
|---|---|
| `<x>`, `<x>-<y>`, `<x>,<y>` | logical CPUs, as the kernel numbers them: `12`, `0-7`, `0,2,4` |
| `core<x>` | a **physical** core, with all its logical CPUs: `core0`, `core0-7`, `core0,2` |
| `numa<x>` | a NUMA domain: `numa0`, `numa0-3`, `numa0,1` |
| `quadrant<x>` | a quadrant, the NUMA domains sharing the same memory controllers: `quadrant0`, `quadrant0-3` |
| `each-core` | every physical core, **one group each** |
| `each-numa` | every NUMA domain, **one group each** |
| `each-quadrant` | every quadrant, **one group each** |
| `all` | every logical CPU, as a single hand-written group: `iterate` walks it one CPU at a time, `selected_cpus_scaling=none` loads them all at once |
| `none` | everything is usable, **no pinning** is performed (default) |

- **Groups.** A space separates two groups; commas, ranges and keywords stay in the same
  group: `numa0 numa1` is two groups, `numa0,1` is one. Each group is a candidate list of
  CPUs for [`selected_cpus_scaling`](#selected_cpus_scaling).
- **A single group written by hand** is flattened into a plain list of logical CPUs, that
  `iterate` walks one CPU at a time: `core0-3` gives 8 benchmarks of one logical CPU,
  `core0 core1 core2 core3` gives 4 benchmarks of one physical core. The `each-*` helpers
  always give groups, even a single one.
- **Topology.** `core<x>`, `numa<x>` and `quadrant<x>` are resolved against the topology
  detected on the target machine, and the `each-*` helpers write `core0 core1 … coreN` for you,
  whatever N is. The number of NUMA domains and quadrants follows two BIOS settings, see
  [NUMA domains and quadrants](cpu-selection.md#numa-domains-and-quadrants).
- **Errors.** A resource the target machine does not have, like `numa8` on 8 domains, is fatal at
  startup. The removed helpers `simple` and `numa-simple` are rejected with the value to
  write instead, see [Removed helpers](#removed-helpers).

What each value selects on a real CPU, with the maps of the resulting benchmarks, is in
[cpu-selection.md](cpu-selection.md).

## selected_cpus_scaling

The iteration method over the CPUs listed by `selected_cpus`; each step produces the list of CPUs to test.

| Value | Effect |
|---|---|
| `iterate` | one benchmark per group (default) |
| `none` | a single benchmark on the whole selection, which must not hold several groups |
| `plus_<x>` | cumulative: `<x>` more groups added at each step; needs groups, and a number of groups multiple of `<x>` |
| `curve` | cumulative: 1, 2, 3, 4, 8, 16 then +16 groups, plus the end of each socket and all of them; needs groups — CPU specific, meant for `each-core` |

A selection holding a single item — one group given by a helper, or one CPU — gives a
single benchmark, whatever the value. `curve` is CPU
specific by nature: its steps follow how a processor behaves as its cores get loaded,
dense at the low end for the single core and turbo behaviour, sparse at the high end, so
it is meant for `selected_cpus=each-core`. See [cpu-selection.md](cpu-selection.md).

## stressor_range

The list of stressor counts to run in the CPU group of each iteration — a stressor being
a thread, a process or a job, the engine decides. The CPU group does not move while the
counts are walked, which is how a thread-count curve is measured at constant CPU
locality.

| Value | Effect |
|---|---|
| `x` | `x` stressors |
| `x-y` | every count from `x` to `y` |
| `x,y,z` | the listed counts |
| `auto` | as many stressors as pinned CPUs |

`auto` requires a pinning: combined with `selected_cpus=none` it is fatal
(`stressor_range=auto but no pinned cpu`).

A **stressor** is one instance of the load inside a benchmark. What that instance is
depends on the engine: a stress-ng worker thread, a fio job. Stressors are
not CPUs: the pinning says *where* the load may run, the stressor count says *how many*
instances run there. Both are free to differ: one stressor on 16 CPUs measures a single
thread with plenty of cache and bandwidth available; 16 stressors on 1 CPU measures
contention.

See [cpu-selection.md](cpu-selection.md#the-same-domains-a-different-load) for a series
of stressor counts walked on the same CPUs.

## stressor_range_scaling

How the stressor counts listed by `stressor_range` become benchmarks.

| Value | Effect |
|---|---|
| `plus_<x>` | one benchmark every `<x>` stressor counts: the `<x>`-th, the `2<x>`-th…; `plus_1`, the default, runs every count |
| `curve` | the 1st, 2nd, 3rd, 4th, 8th, 16th then every 16th stressor count, and the last one |

These are the same scalings as [`selected_cpus_scaling`](#selected_cpus_scaling), computed
by the same function: a step takes the first *k* counts, in the order they are written, and
runs the *k*-th one. `stressor_range=1-8` gives 2, 4, 6, 8 stressors with `plus_2`;
`stressor_range=1-64` gives 1, 2, 3, 4, 8, 16, 32, 48, 64 with `curve`. With `plus_<x>`,
the number of counts must be a multiple of `<x>`. With a single count the keyword has
nothing to iterate over and is ignored; any other value is rejected at startup.

## skip_method

What happens when a benchmark must be skipped, typically a CPU missing the requested
instruction set.

| Value | Effect |
|---|---|
| `bypass` | the benchmark is not executed at all (default) |
| `wait` | it is replaced by a sleep of the same duration |

`wait` keeps the total duration identical across machines with different capabilities,
so runs stay comparable and the thermal history of the chassis is not altered by the
skipped tests. Skipped benchmarks are still reported, with empty values and a `skipped`
marker.

## sync_start

| Value | Effect |
|---|---|
| `none` | start immediately (default) |
| `time` | wait for the next minute boundary |

`time` aligns a benchmark with an external event or with other servers: all machines
waiting for the next minute start at the same second. It applies before **each**
benchmark of the job.

## Engine specific keywords

### disks

`fio` only, and mandatory for it: the block devices to test, one benchmark each.

| Value | Effect |
|---|---|
| `all` | every block device of the target machine that is not mounted and not virtual; a mounted one is skipped with a warning |
| `<device>,<device>` | the listed devices, like `/dev/nvme0n1,/dev/nvme1n1` |

Unlike the other keywords, its value is not lowercased. The fio engine itself is
described in [fio.md](fio.md).

# Legacy and unimplemented keywords

## Renamed keywords

Old names are rejected with a migration message rather than a generic error:

| Old name | New name |
|---|---|
| `hosting_cpu_cores` | `selected_cpus` |
| `hosting_cpu_cores_scaling` | `selected_cpus_scaling` |

## Removed helpers

Removed `selected_cpus` helpers are rejected at startup with the value to write instead,
which selects the same CPUs:

| Removed helper | Write instead |
|---|---|
| `simple` | `selected_cpus=each-core` with `selected_cpus_scaling=curve` |
| `numa-simple` | `selected_cpus=each-numa` with `selected_cpus_scaling=plus_1` |

## Accepted but not implemented

`thermal_start` and `fans_start` are accepted but have **no effect**. They describe a
planned feature: gating the start of a job on the thermal or cooling state of the
chassis, so a benchmark does not start while the server is still hot from the previous
one.

| Key | Value | Effect |
|---|---|---|
| `thermal_start` | `<sensor>:<temp_celsius>,…` | planned: the temperature of each listed sensor authorizing the job to start; no effect yet |
| `fans_start` | `<fan>:<speed>,…` | planned: the speed of each listed fan, in % or rpm, authorizing the job to start; no effect yet |

# Startup validation

The whole job file is validated **before** the first benchmark starts, because a run can
last hours. For every section hwbench checks that the engine exists and loads, that the
engine's own mandatory keywords are present, that no keyword was renamed, that every
keyword is known, and that every value passes its syntax check. The full expansion is
then computed, which also validates the CPU selection against the real topology and the
module parameters against the engine.

Any failure is fatal and names the job and the keyword:

```
Job check_integer_perf: keyword monitor: thermal is not a valid monitoring value
Job check_integer_perf: invalid keyword selcted_cpus
Job check_integer_perf: keyword engine_module_parameter: Engine stressng: float128 module parameter does not exists
```

# Implementation notes

Everything described here lives in `hwbench/config/`.

**Parsing.** `Config` wraps a `configparser.RawConfigParser` built with
`default_section="global"`, so the `[global]` merge is done by `configparser` itself, not
by hwbench. Keyword defaults are the `default_parameters` dictionary of `Config.__init__`;
a keyword absent from it *and* from the job file raises a `KeyError` in its accessor,
which is how `get_engine_module()` implements its "defaults to the engine name" fallback.
All accessors go through `Config.get_directive()`, which lowercases the value.

**The keyword list.** `Config.get_valid_keywords()` is the single source of truth. Adding
a keyword means adding it there, adding a default in `default_parameters` if it has one,
and adding a `validate_<keyword>` function in `config_syntax.py`.

**Validation.** `Config.validate_section()` iterates over the directives of a section and
calls `getattr(config_syntax, f"validate_{directive}")`: the dispatch is by name
convention, so a keyword without its validator raises an `AttributeError` at startup. A
validator returns an empty string when the value is valid, or the message to report, and
the caller turns a non-empty message into a fatal error. Validators receive the `Config`
object and the section name, so they can be cheap (`validate_runtime` only checks
`isnumeric()`) or load the engine to check against reality
(`validate_engine_module_parameter`). Some are deliberately empty stubs
(`validate_thermal_start`), which is exactly why the matching keywords are accepted
without being implemented.

**Engine specific keywords.** An engine declares its own keywords through
`custom_parameters_validators` and `custom_parameters_required` on `EngineBase`; `fio`
uses them for `disks`. They are read from the raw section, so they are **not**
lowercased, and reach the engine through `BenchmarkParameters.get_custom_parameters()`.

**Renamed keywords.** `Config.RENAMED_KEYWORDS` maps the old name to the new one and is
checked before the validity test, so the user gets a migration message instead of
`invalid keyword`.

**Ranges.** `Config.parse_range()` implements the shared `x` / `x-y` / `x,y,z` /
space-separated-groups syntax. It returns a flat list for a single group and a list of
lists for several, a distinction the job expansion relies on
([Groups](cpu-selection.md#groups-the-rule-that-changes-everything)).

**Where it is triggered.** `Benchmarks.parse_jobs_config()` calls `validate_sections()`
then expands everything, and `main()` in `hwbench/hwbench.py` runs it before any
benchmark.
