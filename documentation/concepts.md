# Concepts and vocabulary

The concepts every hwbench user needs, and the words this documentation uses for them.

- [What hwbench is for](#what-hwbench-is-for)
- [A job is an intention](#a-job-is-an-intention)
  - [Choosing the level of a job](#choosing-the-level-of-a-job)
- [Job vs benchmark](#job-vs-benchmark)
- [Constant time per benchmark](#constant-time-per-benchmark)
- [The same job on two different configurations](#the-same-job-on-two-different-configurations)
- [A result is a measurement in a context](#a-result-is-a-measurement-in-a-context)
  - [Comparing environments, not just machines](#comparing-environments-not-just-machines)
- [The full vocabulary](#the-full-vocabulary)
- [Where the words appear](#where-the-words-appear)

# What hwbench is for

hwbench is a benchmark **orchestrator**. It does not measure anything itself: it runs a
campaign, and its intent is to make that campaign reproducible and comparable. Four
things happen in every run:

1. **[Collect the environment](#a-result-is-a-measurement-in-a-context)** — the hardware
   and software context of the target machine, from the BIOS configuration to the firmware and
   kernel versions.
2. **[Adapt the jobs to the real topology](cpu-selection.md)** — the job file describes
   intentions; hwbench instantiates them into individual benchmarks fitting the CPU, the
   NUMA domains and the cores actually present.
3. **[Execute the whole set at constant time](#constant-time-per-benchmark)** — every
   benchmark lasts the same configured duration, so a run has a predictable length and a
   comparable timeline.
4. **[Observe the machine while it runs](monitoring.md)** — temperatures, power
   consumption, fan speeds and CPU frequencies are sampled during each benchmark, when
   [`monitor`](configuration.md#monitor) is enabled.

Performance results are then **tied to the execution context** they were obtained in.
That is what turns single runs into a collection worth keeping, and lets you
[compare environments](#comparing-environments-not-just-machines):

- different hardware: vendor A versus vendor B, CPU A versus CPU B,
- the same machine in different configurations: tuning, BIOS settings, firmware,
- the same machine over time, before and after a change.

The rendering and comparison side is the job of hwgraph, documented separately.

This intent is what drove the design of the configuration file: keywords and helpers are
deliberately high level and topology-relative, so an intention stays expressible without
naming the hardware it will run on. Everything below follows from that.

# A job is an intention

A job expresses **what you want to know**, not how to obtain it on a given server:

> *"I want to measure the integer performance of this CPU."*

```ini
[check_integer_perf]
runtime=120
monitor=all
engine=stressng
engine_module=cpu
engine_module_parameter=int8,int64,int128
selected_cpus=each-numa
selected_cpus_scaling=plus_1
stressor_range=auto
```

Nothing in that job is specific to a machine: no core count, no CPU list, no NUMA domain
count. It states the intention and lets hwbench **instantiate** it, by combining the
keywords with the topology it discovers on the target machine. `each-numa` becomes one
CPU group per NUMA domain of its CPU, `plus_1` adds them one by one, and `auto` becomes
the number of CPUs pinned at each step.

## Choosing the level of a job

A job can be written at any level, from a hardware-agnostic intention down to a very
precise instruction. Both are legitimate; what changes is **what you will be able to
compare afterwards**:

| A job saying… | Written as | Comparable |
|---|---|---|
| "the whole CPU, fully loaded" | `selected_cpus=all` + `selected_cpus_scaling=none` + `stressor_range=auto` | any machine |
| "each NUMA domain on its own" | `selected_cpus=each-numa` | any machine, whatever the domain count |
| "the NUMA domains added one by one" | `selected_cpus=each-numa` + `selected_cpus_scaling=plus_1` | any machine, whatever the domain count |
| "a scaling curve from 1 core to all of them" | `selected_cpus=each-core` + `selected_cpus_scaling=curve` | any machine, the steps adapt |
| "each physical core on its own" | `selected_cpus=each-core` | any machine, whatever the core count |
| "the first NUMA domain" | `selected_cpus=numa0` | machines with a comparable topology |
| "physical core 15" | `selected_cpus=core15` | the same machine, or the same CPU model |
| "logical CPUs 0 to 63" | `selected_cpus=0-63` | the same machine only |

The rule of thumb: **the higher the level, the more comparable the results**, across
machines and across runs. The keywords that do not name any item of the topology (`all`,
`each-core`, `each-numa`, `each-quadrant`, `curve`, `auto`) let hwbench adapt the
instantiation, so the same file keeps its meaning on a 16-core server and on a 128-core
one; `numa<x>`, `quadrant<x>` and `core<x>` name one item, and keep their meaning only on
machines with a comparable topology.

Going low-level is not a mistake, it is a different question: *"is core 15 as fast as its
neighbours?"*, *"does this NUMA domain behave like the others?"*, *"can I reproduce the
pinning of that incident?"* are legitimate intentions, and a hardcoded CPU list is the
right way to express them. Just know what you traded: such a job means something only on
the machines it was written for, and comparing it elsewhere is comparing core 15 of two
different CPUs, not two comparable measurements.

Write the job at the highest level that still answers your question, and drop lower only
for what the high level cannot express.

# Job vs benchmark

A job is a **section** of the job file: a name between square brackets, followed by the
keywords that apply to it, up to the next section.

```ini
# the section name is the job name, and starts the job
[check_integer_perf]
# every keyword below applies to this job...
runtime=120
monitor=all
engine=stressng
engine_module=cpu
engine_module_parameter=int8,int64,int128
selected_cpus=each-numa
selected_cpus_scaling=plus_1
stressor_range=auto

# ...until the next section starts: this is another job
[check_memory_bandwidth_perf]
runtime=120
monitor=all
engine=stressng
engine_module=stream
engine_module_parameter=stream
selected_cpus=each-numa
selected_cpus_scaling=plus_1
stressor_range=auto
```

Both jobs above are written in full, without relying on any default value, so they can
be read on their own.

The format is INI; its rules, comments included, are described in
[configuration.md](configuration.md#file-format).

`[global]` is the only section that is not a job: it carries the default values for all
the others, see [configuration.md](configuration.md#file-format).

| | Job | Benchmark |
|---|---|---|
| What it is | a **description** | an **execution** |
| Where it comes from | one section of the job file | the expansion of a job |
| How many | as many as sections | one to thousands per job |
| Lasts | the sum of its benchmarks | `runtime` seconds |
| Named | by you, as the section name | `<job_name>_<number>`, by hwbench |

A job never runs. It is a recipe that hwbench multiplies by the CPU selection, the engine
module parameters and the stressor counts to obtain the benchmarks, which are the only
things that are actually executed, timed, monitored and reported.

On a server with 2 NUMA domains, the two jobs above expand into **8 benchmarks**: 2 CPU
groups × 3 parameters for `check_integer_perf`, and 2 CPU groups × 1 parameter for
`check_memory_bandwidth_perf`. hwbench prints each one as it starts; on a dual-socket
Intel Xeon Gold 6240, 36 physical cores and 72 logical CPUs:

```
[check_integer_perf_0] stressng/cpu/int8(M):  36 stressor pinned on CPU [0-17, 36-53] for 120s
[check_integer_perf_1] stressng/cpu/int64(M):  36 stressor pinned on CPU [0-17, 36-53] for 120s
[check_integer_perf_2] stressng/cpu/int128(M):  36 stressor pinned on CPU [0-17, 36-53] for 120s
[check_integer_perf_3] stressng/cpu/int8(M):  72 stressor pinned on CPU [0-71] for 120s
[check_integer_perf_4] stressng/cpu/int64(M):  72 stressor pinned on CPU [0-71] for 120s
[check_integer_perf_5] stressng/cpu/int128(M):  72 stressor pinned on CPU [0-71] for 120s
[check_memory_bandwidth_perf_6] stressng/stream/stream(M):  36 stressor pinned on CPU [0-17, 36-53] for 120s
[check_memory_bandwidth_perf_7] stressng/stream/stream(M):  72 stressor pinned on CPU [0-71] for 120s
```

Each benchmark lasts the 120 seconds of `runtime`, so `check_integer_perf` lasts 12
minutes and the whole run 16 — see [constant time per benchmark](#constant-time-per-benchmark).

How the CPU selection and the stressor counts expand a job is the subject of
[cpu-selection.md](cpu-selection.md).

# Constant time per benchmark

A benchmark always runs for [`runtime`](configuration.md#runtime) seconds — the same
duration whatever the engine, the parameter, the number of stressors or the speed of the
machine. hwbench does not stop early when a tool has done its work: the engines are
driven by time (`--timeout` for stress-ng, `--time_based` for fio), and a benchmark that
has to be skipped can even be replaced by a wait of the same duration with
[`skip_method=wait`](configuration.md#skip_method).

This is a deliberate design choice, for two reasons.

**It makes results comparable.** A measurement is a rate observed over a fixed window.
With the same window everywhere, a faster machine does *more work* inside the window
instead of finishing earlier, so the numbers can be put side by side. It also applies to
the environment: temperature rise, power draw and fan ramp-up depend on how long the
load lasted, so comparing the thermal behaviour of two servers only makes sense if both
were loaded for the same time.

**It makes the end time predictable.** The duration of a run is known before it starts:
number of benchmarks × `runtime`. hwbench prints it as a duration and as an estimated
end time, so you can plan around it — sixteen minutes for the run below, hours for a
real campaign — and book a lab or a CI slot accordingly:

```
hwbench: 2 jobs, 8 benchmarks, ETA 0h 16m 00s, estimated end at 2026-09-17 18:31:02
```

Two things to keep in mind: `runtime` is **per benchmark**, so raising it is multiplied
by the whole expansion; and the announced ETA counts only benchmark time, so the real
end lands slightly later, the extra being the engine startup, the version detection and
any [`sync_start`](configuration.md#sync_start) wait. Benchmarks that are fully skipped
are excluded from the estimate.

# The same job on two different configurations

Because the instantiation depends on the topology, the **same job produces a different
number of benchmarks on different configurations**. And a configuration is not
necessarily another machine: a BIOS setting is enough to change the topology of the
server you already have — disabling SMT halves the logical core count, a NUMA-per-socket
setting multiplies the domains, disabling cores changes the count.

| | Configuration A | Configuration B |
|---|---|---|
| topology | 36 cores, 2 NUMA domains | 64 cores, 8 NUMA domains |
| `selected_cpus=each-numa` | 2 CPU groups | 8 CPU groups |
| `engine_module_parameter=int8,int64,int128` | 3 parameters | 3 parameters |
| benchmarks for `check_integer_perf` | 6 | 24 |
| CPUs loaded by the last benchmark | 72 | 128 |

The counts differ, the intention does not. That is exactly what makes the comparison
possible: both runs contain a job named `check_integer_perf` meaning "integer
performance of this CPU", and every benchmark carries the `job_name` it was instantiated
from.

**hwgraph relies on this.** It groups the benchmarks of every trace by `job_name` and
compares the groups, so two configurations that did not run the same number of
benchmarks can still be put on the same graph. The consequence for you: keep the job
*names* and their intention stable across the runs you intend to compare, and let the
benchmark count vary. See the hwgraph documentation for what it does with those groups.

**You decide what is being compared.** hwbench keeps the intention stable and records
the context of each run; choosing *which* configurations to run is what defines the
comparison. Run the same job file on the same hardware with one BIOS setting changed and
you are measuring that setting. Run it on two different servers and you are comparing
the hardware. Run it on the same machine before and after a firmware update and you are
measuring the firmware. The job file does not change — only the configurations you
choose to put side by side.

# A result is a measurement in a context

A performance number alone means nothing: the same server, benchmarked twice, answers
differently after a kernel upgrade, a BIOS setting change, a firmware update or a
replaced heatsink. So hwbench never reports performance alone — at startup it
**collects the execution context**, hardware and software, and stores it in the same
result file as the metrics.

What is collected, at a high level:

| | Collected |
|---|---|
| **Server identity** | vendor, product, serial, chassis (DMI) |
| **BIOS** | version, release, and the full **BIOS configuration** when the vendor allows it |
| **Firmware** | BMC and PDU model, serial and firmware versions |
| **CPU** | vendor, model, logical and physical core counts, sockets, NUMA domains and their cores, NUMA distances, CPU flags |
| **Memory** | kernel memory info, DMI memory description |
| **Devices** | PCI devices, block devices, NVMe details, IPMI sensor list |
| **Kernel** | version, release, command line, build configuration, `/proc/sys` tree, boot logs |
| **Software** | installed packages, and the version of every benchmarking tool used |
| **Tuning** | what hwbench changed on the system before the run, and whether tuning was enabled at all |

Everything lands in the output directory, and the identity part is embedded in
`results.json` next to the `bench` results, so a result file is self-describing: months
later it still says which machine, which BIOS, which kernel and which tool versions
produced those numbers.

## Comparing environments, not just machines

This is what makes the second strong use of hwbench possible. Run the **same job file**
before and after a change:

- a kernel or microcode upgrade,
- a BIOS setting, a firmware update,
- a hardware change — a CPU swap, more DIMMs, a different cooling,
- a tuning change, or `--no-tuning` versus the default.

The intention is unchanged, the context is not. Both runs carry their own context, so
the difference in results can be attributed to the change instead of being guessed. It
works even when the topology itself changed: the job is re-instantiated for the new
machine, and the benchmarks still group under the same job names.

That is the practical reason to write jobs at a high level: an intention like "load the
whole CPU" or "one step per NUMA domain" survives a core count change, a BIOS
reconfiguration or a CPU replacement without being edited, so the *only* thing that
differs between the two runs is what you actually changed. A job pinned on
`selected_cpus=0-63` cannot make that claim: after the change, it may no longer describe
the same fraction of the machine.

# The full vocabulary

| Term | Definition |
|---|---|
| **target machine** | the server a job file is run on, whose topology the jobs are instantiated for |
| **run** | one hwbench invocation: one job file, one output directory, one `results.json` |
| **job** | one section of the job file, i.e. one description of a set of tests |
| **benchmark** | one executed test: one engine module parameter, one stressor count, one CPU pinning, `runtime` seconds |
| **engine** | where the logic of a benchmark lives (`stressng`, `fio`, `spike`, `sleep`): either a wrapper around an external tool, or hwbench's own code |
| **engine module** | one testing mode on that engine (`cpu`, `stream`, `memrate`, `cmdline`, …) |
| **engine module parameter** | a parameter handed to the engine module; what it means is defined by the engine, see its own page |
| **stressor** | one instance of the load inside a benchmark; the count comes from `stressor_range` |
| **pinning** | the list of logical CPUs a benchmark is restricted to, from `selected_cpus` |
| **monitoring** | the environmental metrics collected during a benchmark, when `monitor` is enabled |
| **tuning** | the system settings applied once, before the run, to make results reproducible |

The engine hierarchy always reads the same way, and appears as such in hwbench's output:

```
engine / engine_module / engine_module_parameter
stressng / cpu        / int128
```

# Where the words appear

Knowing which word applies to which artifact saves time when reading a result:

| Artifact | Granularity |
|---|---|
| the job file (`-j`) | one section per **job** |
| `expanded_job_file.conf` | one section per **benchmark** |
| `results.json`, `bench` key | one entry per **benchmark**, keyed `<job>_<number>` |
| the engine output files | one set per **benchmark** |
| `tuning/` | one per **run** |

Inside a `bench` entry, `job_name` is the job the benchmark came from and `job_number`
is the benchmark's own index in the whole run, not in its job: above, the benchmarks of
`check_memory_bandwidth_perf` are numbered 6 and 7, not 0 and 1.
