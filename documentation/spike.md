# spike: load spikes to study the cooling

The `spike` engine is a custom benchmark implemented in hwbench: it applies cycles of
load and idle to the CPUs, to observe how the cooling of the server reacts — how the fan
algorithm follows the load, and what it costs in fan speed and power. It measures no
performance: its results are the monitoring metrics collected during the benchmark and
the timing of the cycles. The load itself is run by stress-ng.

- [Modes](#modes)
- [Manual mode: fixed cycles](#manual-mode-fixed-cycles)
- [Auto mode: cycles driven by the fans](#auto-mode-cycles-driven-by-the-fans)
- [Metrics](#metrics)
- [Example](#example)
- [Implementation notes](#implementation-notes)

Related pages: [configuration.md](configuration.md) (the keywords of the job file),
[engines.md](engines.md) (the engine / module / parameter model) and
[monitoring.md](monitoring.md) (the metrics collected during the benchmark).

# Modes

The `spike` engine has a single module, `cpu`, with a single parameter, `cpu`. The cycles
are described by [`engine_module_parameter_base`](configuration.md#engine_module_parameter_base):

| Value | Effect |
|---|---|
| `high:<seconds> low:<seconds>` | manual mode: each cycle loads the CPUs for `high` seconds, then leaves them idle for `low` seconds |
| `auto` | auto mode: each cycle loads the CPUs until the fans speed up by 5%, then waits for them to slow down |
| `auto:<percent>` | auto mode, the load stopping when the fans speed up by `<percent>`% |

In both modes, the load is `stress-ng --cpu <stressors> --cpu-method matrixprod`, pinned on
the CPUs selected by `selected_cpus`, with as many workers as the stressor count of the
benchmark.

> ℹ️ **Info**
>
> The monitoring must be enabled with [`monitor=all`](configuration.md#monitor): the auto
> mode reads the fan speeds from the BMC to drive its cycles, and both modes are only
> meaningful with the fans, thermal and power metrics collected during the cycles.

# Manual mode: fixed cycles

```ini
engine_module_parameter_base=high:10 low:5
```

Each cycle lasts `high` + `low` seconds, and the cycles are repeated up to the `runtime`
of the benchmark: with `runtime=60`, the example above runs 4 cycles of 10 seconds loaded
and 5 seconds idle.

> ℹ️ **Info**
>
> The `runtime` must be a multiple of the cycle, so the benchmark ends on a complete
> cycle: otherwise the job is rejected at startup with
> `Cycles (15s) are not modulo the runtime (70s)`. A cycle of 0 second is rejected too:
> `No cycle detected, check low and high values`.

# Auto mode: cycles driven by the fans

```ini
engine_module_parameter_base=auto:10
```

1. **Calibration**: the fans are read every second for 33 seconds, the CPUs idle, and
   their average speed becomes the idle reference.
2. **Load**: stress-ng is started, and runs until the total fan speed reaches the
   reference plus `<percent>`%.
3. **Cool down**: the load is stopped, and hwbench waits for the fans to come back
   within 1% of the reference.
4. The cycle starts again from step 2, until the next check would go beyond the
   `runtime`.

After the calibration, the fans are read every 11 seconds, during the load and the cool
down alike: the time of each phase is known to within 11 seconds.

Unlike the manual mode, the length of the cycles is decided by the server: it shows how
long the fan algorithm takes to react to a load, and to calm down after it.

> ℹ️ **Info**
>
> The `<percent>` must be greater than 1: otherwise the job is rejected at startup with
> `fan_ratio should be greater than 1%`.

# Metrics

Besides the monitoring metrics, the result of a `spike` benchmark holds the timing of its
cycles:

| Key | Value | Effect |
|---|---|---|
| `time_to_high` | seconds | manual mode: the `high` value; auto mode: for every cycle, the time the fans took to reach the target speed |
| `time_to_low` | seconds | manual mode: the `low` value; auto mode: for every cycle, the time the fans took to come back to their idle speed |

# Example

hwbench ships a sample job file, [`configs/spike.conf`](../configs/spike.conf):

```ini
[global]
runtime=300
monitor=all

[spike]
engine=spike
engine_module=cpu
engine_module_parameter_base=high:10 low:5
selected_cpus=each-core
selected_cpus_scaling=curve
stressor_range=auto
```

| Key | Value | Effect |
|---|---|---|
| `runtime` | `300` | each benchmark lasts 5 minutes, that is 20 cycles of 15 seconds |
| `monitor` | `all` | the fans, thermal and power metrics are collected during the cycles |
| `engine_module_parameter_base` | `high:10 low:5` | manual mode: 10 seconds loaded, 5 seconds idle, per cycle |
| `selected_cpus`, `selected_cpus_scaling` | `each-core`, `curve` | the spikes are repeated on a growing number of physical cores: 1, 2, 3, 4, 8, 16, then 16 more at each step, up to the whole CPU |
| `stressor_range` | `auto` | one stress-ng worker per pinned logical CPU, so each spike loads its cores fully |

The job answers *"how does the cooling react to short load spikes, as their size grows?"*:
a spike on a single core may not move the fans at all, while a spike on the whole CPU
shows the full reaction of the fan algorithm, and what it costs in fan speed and power. On
the AMD EPYC 8534P of [cpu-selection.md](cpu-selection.md), the curve has 9 steps, that is
9 benchmarks and 45 minutes;
[`uv run hwbench -j configs/spike.conf --dry-run`](cpu-selection.md#previewing-a-job-file---dry-run)
shows them on the target machine.

The same study in auto mode lets the fans decide the length of the cycles:

```ini
[global]
runtime=600
monitor=all

[spike_auto]
engine=spike
engine_module=cpu
engine_module_parameter_base=auto:10
selected_cpus=all
selected_cpus_scaling=none
stressor_range=auto
```

After 33 seconds of calibration, all the CPUs are loaded until the fans speed up by 10%,
then left idle until they calm down, as many times as the 10 minutes allow. `time_to_high`
and `time_to_low` then give, cycle after cycle, how long the fan algorithm takes to react
to the load and to calm down after it.

> ℹ️ **Info**
>
> Give the auto mode a long `runtime`: the calibration alone takes 33 seconds, and a
> cycle lasts as long as the fans need to speed up and slow down, often much longer than
> the fixed cycles of the manual mode.

# Implementation notes

**Files.** The engine is `hwbench/engines/spike.py`. It declares `stress-ng` as its
binary, which is checked before the run like for any engine.

**Parameters.** `Spike.parse_parameters()` reads `high:`, `low:` and `auto` from
`engine_module_parameter_base`. It is called by `validate_module_parameters()` during
the expansion, so a wrong cycle or fan ratio is reported at startup.

**Cycles.** `manual_spike()` runs `stress-ng -t <high>` then sleeps `low` seconds, cycle
after cycle; `auto_spike()` starts stress-ng in the background and kills it when the
fans, read through the BMC with `read_fans()`, reach the target. Both measure the time
with `CLOCK_MONOTONIC_RAW` and stop before the next cycle would exceed the `runtime`,
with a 2 second margin.
