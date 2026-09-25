# stress-ng: CPU and memory micro-benchmarks

The `stressng` engine drives [stress-ng](https://github.com/ColinIanKing/stress-ng), a
third-party tool providing CPU and memory micro-benchmarks. hwbench builds the stress-ng
command line of each benchmark from the job, pins it on the selected CPUs, runs it for
the `runtime` of the job and turns its output into metrics.

- [Modules](#modules)
- [Running a benchmark](#running-a-benchmark)
- [Metrics](#metrics)
- [Constraints](#constraints)
- [Example](#example)
- [Implementation notes](#implementation-notes)

Related pages: [configuration.md](configuration.md) (the keywords of the job file),
[engines.md](engines.md) (the engine / module / parameter model) and
[cpu-selection.md](cpu-selection.md) (the pinning).

# Modules

| Value | Effect |
|---|---|
| `cpu` | CPU micro-benchmarks, one method per benchmark: integer, floating point, matrix, FFT… |
| `qsort` | sorting of random data with qsort |
| `stream` | memory bandwidth, the STREAM benchmark: read, write and compute rates |
| `memrate` | memory read and write rates, for every access size and method |
| `vnni` | the vector neural network instructions of the processor, with or without AVX |

Each module accepts its own `engine_module_parameter` values, listed in
[configuration.md](configuration.md#engine_module_parameter): the methods of
`stress-ng --cpu-method list` for `cpu`, a static list gated by CPU flags for `vnni`, and
the module name only for the others.

# Running a benchmark

Every benchmark runs one stress-ng command:

```
taskset -c <cpus> stress-ng --timeout <runtime> --metrics --yaml <benchmark>.yaml --<module> <stressors> <module options>
```

| Key | Value | Effect |
|---|---|---|
| `taskset -c` | the CPUs of the benchmark | the pinning built from `selected_cpus` and `selected_cpus_scaling`; absent with `selected_cpus=none` |
| `--timeout` | `runtime` | the benchmark lasts exactly `runtime` seconds |
| `--metrics`, `--yaml` | the benchmark name | the metrics printed by stress-ng, that hwbench parses, and a YAML copy of them kept on disk |
| `--<module>` | the stressor count, from `stressor_range` | the number of stress-ng workers: `--cpu 16`, `--stream 16`… |
| module options | from the module and its parameter | `--cpu-method <method>` for `cpu`, `--memrate-flush` for `memrate`, `--vnni-method` with the method name without its `noavx_` or `avx_` prefix, plus `--vnni-intrinsic` for the `avx_` methods, for `vnni` |

A stressor is one stress-ng worker: `stressor_range=auto` runs one worker per pinned
logical CPU.

# Metrics

The metrics are added to the `bench` section of `results.json`:

| Key | Value | Effect |
|---|---|---|
| `bogo ops/s` | operations per second | with `cpu`, `qsort` and `vnni`: the rate reported by stress-ng for all the workers |
| `detail` → `read`, `write`, `Mflop/s` | a list, one rate per worker, in MB/s and Mflop/s | with `stream`: the rates of each worker |
| `avg_read`, `avg_write`, `avg_Mflop/s` | MB/s, Mflop/s | with `stream`: the average rates over the workers |
| `sum_read`, `sum_write`, `sum_Mflop/s` | MB/s, Mflop/s | with `stream`: the sum of the rates of all the workers |
| `avg_total`, `sum_total` | MB/s | with `stream`: read + write, averaged or summed |
| `<test>` → `avg_speed`, `sum_speed` | MB/s | with `memrate`, for every test (`read64`, `write128nt`…): the rate of one worker, and of all of them |
| `effective_runtime` | seconds | with every module: the duration stress-ng actually ran |

A skipped benchmark gets the same keys, with zero values and `skipped` set, so the
graphs and comparisons do not break on a machine where a test could not run.

> ℹ️ **Info**
>
> The performance metrics of stress-ng are **indicative**: bogo operations and rates are
> defined by the code of each stress-ng method, which evolves from one version to the
> next, and so do the values it reports. To compare different runs, use the **same
> version of stress-ng** on all of them. The version used is kept in the output
> directory, in the `<benchmark>-version-stdout` file of each benchmark.

# Constraints

> ℹ️ **Info**
>
> stress-ng 0.17.04 or later is required. The version is checked when each benchmark
> runs, and an older one is reported with
> `WARNING: skipping benchmark …, needs stress-ng >= 0.17.04`.

> ℹ️ **Info**
>
> Some parameters depend on the target machine. A `cpu` method the installed stress-ng
> does not provide is rejected at startup, the list depending on the version and the
> build of stress-ng. A `vnni` method the CPU cannot run is skipped:
> `WARNING: CPU does not support method …, perf will be 0`.

The job file is also rejected at startup when:
- a `stream` benchmark has a `runtime` below 5 seconds: `StressNGStream needs at least a 5s of run time`;
- a benchmark is pinned beyond the logical CPUs of the target machine: `Cannot pin on core #<cpu> we only have <n> cores`.

# Example

```ini
[check_integer_perf]
runtime=120
engine=stressng
engine_module=cpu
engine_module_parameter=int8,int64,int128
selected_cpus=each-numa
selected_cpus_scaling=plus_1
stressor_range=auto
```

One benchmark per NUMA domain added and per method, each running
`stress-ng --cpu <logical CPUs of the step> --cpu-method <method>`, pinned on the domains
of its step.
[`uv run hwbench -j <job_file> --dry-run`](cpu-selection.md#previewing-a-job-file---dry-run)
shows them before running.

# Implementation notes

**Files.** The engine is `hwbench/engines/stressng.py`, one file per module:
`stressng_cpu.py`, `stressng_qsort.py`, `stressng_stream.py`, `stressng_memrate.py` and
`stressng_vnni.py`.

**Command line.** `StressNG.run_cmd()` builds the common part, `--timeout`, `--metrics`
and `--yaml`, and ends with `get_taskset()`, so every module that extends it is pinned.
Each module appends its own option and the stressor count, read through
`get_engine_instances_count()`.

**Version.** `need_skip_because_version()` compares the version parsed from
`stress-ng --version` with 0.17.04, when each benchmark runs, and returns
`echo skipped benchmark` instead of the stress-ng command when it is older; `cpu` and
`qsort` still append their own options to it, `stream`, `memrate` and `vnni` do not.

**Metrics.** `StressNG.parse_cmd()` reads the `stress-ng: metrc:` line of the output for
`bogo ops/s` and `effective_runtime`; `stream` and `memrate` parse their own lines for
their rates.

**Parameters.** `EngineModuleCpu.init()` runs `stress-ng --cpu-method list` at startup to
build the list of methods; `EngineModuleVNNI` builds its list in its constructor, each
method checked against the CPU flags.
