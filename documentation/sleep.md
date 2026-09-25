# sleep: no load, on purpose

The `sleep` engine applies no load at all: each benchmark runs the `sleep` command for the
`runtime` of the job. It measures no performance, but it is useful in two cases:

| Use | Effect |
|---|---|
| a pause between two jobs | the server cools down, so a job does not start while it is still hot from the previous one |
| an idle reference of the environment | with the monitoring enabled, the thermal, fans and power metrics of the idle server, to compare the loaded benchmarks with |

- [Running a benchmark](#running-a-benchmark)
- [Metrics](#metrics)
- [Example](#example)
- [Implementation notes](#implementation-notes)

Related pages: [configuration.md](configuration.md) (the keywords of the job file),
[engines.md](engines.md) (the engine / module / parameter model) and
[monitoring.md](monitoring.md) (the metrics collected during the benchmark).

# Running a benchmark

The `sleep` engine has a single module, `sleep`, with a single parameter, `sleep`: since
they are the defaults, `engine=sleep` alone is a complete job. Every benchmark runs:

```
taskset -c <cpus> sleep <runtime>
```

| Key | Value | Effect |
|---|---|---|
| `taskset -c` | the CPUs of the benchmark | the pinning built from `selected_cpus`, absent with `selected_cpus=none` |
| `sleep` | `runtime` | the benchmark lasts exactly `runtime` seconds |

> ℹ️ **Info**
>
> A single `sleep` process runs, whatever the stressor count of the benchmark:
> `stressor_range` has no effect on the load, it is only reported in the results.

# Metrics

| Key | Value | Effect |
|---|---|---|
| `bogo ops/s` | the `runtime` | a placeholder, so the results have the same shape as the other engines: no performance is measured |

With `monitor=all`, the monitoring metrics of the idle server are added like for any
benchmark.

# Example

```ini
[global]
runtime=120
monitor=all

[idle_reference]
engine=sleep

[check_integer_perf]
engine=stressng
engine_module=cpu
engine_module_parameter=int64
selected_cpus=all
selected_cpus_scaling=none
stressor_range=auto

[cool_down]
engine=sleep
runtime=300
```

`idle_reference` records 2 minutes of the idle server, `check_integer_perf` loads all
the CPUs, and `cool_down` leaves the server idle for 5 minutes before the next run.

# Implementation notes

**Files.** The engine is `hwbench/engines/sleep.py`, with the `sleep` binary checked
before the run like for any engine, and its version read from `sleep --version`.

**Command line.** `Sleep.run_cmd()` builds `sleep <runtime>` and prefixes it with
`get_taskset()`, like the other engines.

**Skipped benchmarks.** `skip_method=wait` does not use this engine: a benchmark skipped
with `wait` is replaced by a sleep of the same duration inside hwbench itself.
