# Engines: the three-level model

An *engine* is where the logic of a benchmark lives. It serves one of two purposes:

- **Driving a third-party benchmark**, like `stressng` for stress-ng and `fio` for fio:
  hwbench builds the tool's command line from the job, pins it on the selected CPUs,
  runs it for the job's `runtime` and turns its output into metrics. The benchmark
  itself is the tool's.
- **Implementing a custom benchmark in hwbench**, when no tool measures what is needed:
  `spike` applies its own cycles of load and idle to observe how the cooling reacts, and
  `sleep` applies no load at all, on purpose. The logic is hwbench's own Python code,
  which may still run a tool underneath — `spike` loads the CPUs with stress-ng.

Both kinds get the same services from hwbench, described in
[What an engine does for you](#what-an-engine-does-for-you), and are selected the same
way: a job picks what to run through three keywords, from the most general to the most
specific.

- [The three levels](#the-three-levels)
- [Why three levels](#why-three-levels)
- [Static or discovered parameters](#static-or-discovered-parameters)
- [What an engine does for you](#what-an-engine-does-for-you)
- [Available engines](#available-engines)
- [Implementation notes](#implementation-notes)

Vocabulary used here is defined in [concepts.md](concepts.md); the keywords themselves
are in [configuration.md](configuration.md).

# The three levels

Each of the three keywords answers its own question, shown here with the values of the benchmark printed below:

| Key | Value | Effect |
|---|---|---|
| `engine` | `stressng` | which benchmark logic; **mandatory** |
| `engine_module` | `cpu` | which testing mode on that engine; defaults to the engine name |
| `engine_module_parameter` | `int128` | what is handed to that mode; defaults to the module name |

hwbench prints exactly this hierarchy, `engine/engine_module/engine_module_parameter`,
for every benchmark it starts; `(M)` marks a benchmark with the monitoring enabled:

```
[check_integer_perf_0] stressng/cpu/int128(M):  16 stressor pinned on CPU [0-7, 64-71] for 120s
```

The fallbacks are what makes short jobs possible: `engine=sleep` alone is a complete
job, because the `sleep` engine has a `sleep` module which has a `sleep` parameter.

# Why three levels

Because the three levels do not vary for the same reasons, and only the last one is
meant to be listed in a job:

- The **engine** decides what actually runs, how the output is turned into metrics, and
  what "one stressor" means for it — a thread for stress-ng, a fio job for fio.
- The **module** groups the modes sharing a command line shape and a result format. In
  stress-ng, `cpu` reports bogo-ops while `stream` reports MB/s and Mflop/s: same engine,
  different metrics, therefore different modules.
- The **parameter** is what the module is given, and its meaning is defined by the
  engine, so it is documented on the engine's own page. It accepts a list, so a whole
  comparison lives on one line and every item becomes its own benchmark:

```ini
[check_integer_perf]
engine=stressng
engine_module=cpu
engine_module_parameter=int8,int16,int32,int64,int128
```

One job, five benchmarks per CPU group, all directly comparable because everything else
is identical.

A fourth keyword, `engine_module_parameter_base`, exists for the engines whose input is
not a keyword but a command line or a custom syntax. It is a static string, shared by
every benchmark of the job, and is only interpreted by the implementation of some engines
in hwbench; the others ignore it:

- `spike` parses its load/idle cycle description, `high:<seconds> low:<seconds>`, `auto`
  or `auto:<percent>`.
- `fio` takes the fio options of the test, and enforces the ones hwbench must control:
  `--runtime`, `--time_based`, `--numjobs`, `--name`, `--filename`, `--invalidate`,
  `--log_avg_msec`, the output format and the logs. A value given in the job file for one of them is replaced, with a
  message.

# Static or discovered parameters

Depending on the engine, the valid `engine_module_parameter` values are either a static
list written in hwbench, or discovered at startup from the tool installed on the target
machine. Today, only `stressng`/`cpu` discovers its list:

| Module | Parameters | Where the list comes from |
|---|---|---|
| `stressng`/`cpu` | **discovered** | asked to the tool at startup: `stress-ng --cpu-method list` |
| `stressng`/`vnni` | static | a list written in hwbench, each entry gated by a CPU flag (`avx512bw`, `avx512_vnni`, `avx_vnni`) |
| `stressng`/`stream`, `memrate`, `qsort` | static | a single parameter, the module name |
| `fio`/`cmdline` | static | a single parameter, the real input is the command line |
| `spike`/`cpu`, `sleep`/`sleep` | static | a single parameter, the module name |

A discovered list has two practical consequences:

- **A parameter can exist on one server and not on another**, the list depending on the
  version and the build of the tool. hwbench validates the list of the job file against
  the real one at startup, and refuses to run on a typo, or on a method the tool does not
  provide. `configs/curve-cpu.conf` asks for `float128`, that a stress-ng 0.17.06 built
  without it does not provide:

  ```
  Job cpu: keyword engine_module_parameter: Engine stressng: float128 module parameter does not exists
  ```

- **`engine_module_parameter=all`** asks for every parameter the tool exposes on the
  target machine. Convenient to explore a tool, risky for a long run: the count depends
  on the tool installed.

A static list does not depend on the tool, but some entries depend on the processor.
When a parameter exists but the CPU cannot run it, like a `vnni` method gated by a flag
the CPU lacks, the job is not refused. On an Intel Xeon Gold 6240, which has
`avx512_vnni` but not `avx_vnni`, `engine_module_parameter=avx_vpaddb128` gives at
startup:

```
WARNING: CPU does not support method avx_vpaddb128, perf will be 0
```

The benchmark is not dropped: it is *skipped*, reported with empty values, and
[`skip_method`](configuration.md#skip_method) decides whether the time is given back or
spent waiting.

# What an engine does for you

Whatever the tool, the engine layer provides the same services, which is what makes
results comparable across engines:

- **binary check** at startup, so a missing tool is reported before the first benchmark;
  the version of the tool is read when each benchmark runs, and kept in the output
  directory;
- **CPU pinning**, by prefixing the command with `taskset -c <cpu list>` built from
  `selected_cpus` and its scaling mode, `selected_cpus_scaling`;
- **runtime enforcement**, so every benchmark lasts `runtime` seconds;
- **metric extraction** from the tool's output into the `bench` section of
  `results.json`, plus the raw output kept on disk for later analysis;
- **monitoring** started and stopped around the benchmark when `monitor` is enabled;
- **empty results on skip**, with the same keys as a real result, so graphs and
  comparisons do not break on a machine where a test could not run.

> ℹ️ **Info**
>
> Running every benchmark for a constant time is **mandatory**: it is what makes the
> results comparable across machines and the end of a run predictable, see
> [Constant time per benchmark](concepts.md#constant-time-per-benchmark). The **engine is
> responsible** for enforcing it: whatever the speed of the machine, its benchmark must
> last `runtime` seconds. A new engine has to respect this constraint.

# Available engines

| Value | Effect |
|---|---|
| `stressng` | CPU and memory micro-benchmarks, see [stressng.md](stressng.md) |
| `fio` | storage benchmarking, see [fio.md](fio.md) |
| `spike` | applies load spikes to study the cooling: how the fan algorithm reacts, and what it costs in fan speed and power, see [spike.md](spike.md) |
| `sleep` | applies no load: a pause between two jobs, or an idle reference of the environment — no performance is measured, see [sleep.md](sleep.md) |

There is no command to list them: the engines are the files of `hwbench/engines/` exposing
an `Engine` class, and the value of `engine` is the name of that file.

# Implementation notes

**Loading.** `Config.load_engine()` imports `hwbench.engines.<engine>` dynamically and
instantiates its `Engine` class. The engine name is therefore the **file name**, and
`validate_engine()` in `hwbench/config/config_syntax.py` asserts
`engine.get_name() == value`, so the file name, the name passed to `EngineBase` and the
keyword value must agree.

**Structure.** In `hwbench/bench/engine.py`, `EngineBase` holds the binary name and a
dict of modules filled with `add_module()`, while `EngineModuleBase` holds a list of
parameters filled with `add_module_parameter()`. `get_module_parameters()` called with
`special_keywords=True` is what adds `all` to the list the validator accepts, while the
expansion iterates over the real list only.

**Initialisation order matters.** The constructor must stay cheap: anything requiring the
tool goes into `EngineModuleBase.init()`, called by `Benchmarks.parse_jobs_config()`
during the expansion. `stressng`/`cpu` relies on this to run
`stress-ng --cpu-method list` from `list_module_parameters()`, while `stressng`/`vnni`
can build its list in the constructor since it only reads CPU flags.

**Validation hooks.** An engine module may implement `validate_module_parameters()`,
called for every benchmark at expansion time. `EngineModulePinnable` uses it to reject a
pinning beyond the logical CPU count; `EngineModuleVNNI` uses it to warn that a method
unsupported by the CPU will report 0. An engine may also add a dimension to the
expansion with `generate_benchmarks()`, as `fio` does to produce one benchmark per disk.

**Running.** The common machinery is `External` in `hwbench/utils/external.py`, extended
by `ExternalBench` in `hwbench/bench/benchmark.py`. `External.run()` optionally runs
`run_cmd_version()`, then `run_cmd()`, writes `<benchmark>-stdout`, `-stderr`,
`-version-stdout` and `-version-stderr` in the output directory, and hands the output to
`parse_cmd()`, whose returned dict becomes the benchmark result. `LC_ALL=C` is forced so
output parsing does not depend on the locale.

**Stressor count.** The resolved count is stored in `BenchmarkParameters` and read by
the engines through `get_engine_instances_count()`; each engine maps it to its own notion
of an instance, such as `--cpu N` for stress-ng or `--numjobs` for fio.

**Pinning is the engine's job.** `ExternalBench.get_taskset()` prefixes the command with
`taskset -c`, but each engine must call it in its `run_cmd()`. The `stressng` modules
get it by extending `StressNG.run_cmd()`, which ends with `get_taskset()`: a module that
rebuilt its command line from scratch would silently lose the pinning.
`test_memory_modules_pinning` guards this for `stream` and `memrate`.

**Adding an engine.** Create `hwbench/engines/<name>.py` exposing an `Engine(EngineBase)`
class that calls `super().__init__("<name>", "<binary>")` and registers its modules; each
module implements `run_cmd()`, `run()` and `fully_skipped_job()`, called for every
benchmark, and relies on an `ExternalBench` subclass implementing `run_cmd()`,
`parse_cmd()` and `empty_result()`. No registry has to be updated: the dynamic import makes
the new engine usable as `engine=<name>` immediately, and mandatory engine specific
keywords are declared with `custom_parameters_required`
([configuration.md](configuration.md#implementation-notes)).
