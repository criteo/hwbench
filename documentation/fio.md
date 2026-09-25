# fio: storage benchmarking

The `fio` engine drives [fio](https://github.com/axboe/fio), a third-party storage
benchmark: hwbench builds the fio command line of each benchmark from the job, runs it
on every disk to test for the `runtime` of the job, and keeps the fio results.

- [Modes](#modes)
- [Command line](#command-line)
- [Metrics](#metrics)
- [Example](#example)
- [Implementation notes](#implementation-notes)

Related pages: [configuration.md](configuration.md) (the keywords of the job file, and
[`disks`](configuration.md#disks)), [engines.md](engines.md) (the engine / module /
parameter model).

> ℹ️ **Info**
>
> fio 3.19 or later is required. The version is checked when each benchmark runs: with an
> older one, the benchmark is reported with `WARNING: skipping benchmark …, needs fio >= 3.19`
> and gives an empty result.

# Modes

The fio mode is selected with `engine_module`:

| Value | Effect |
|---|---|
| `cmdline` | the fio options of the test are given in `engine_module_parameter_base`, see [Command line](#command-line) |

Two more modes are planned, not implemented yet: running an existing fio job file, and
defining the jobs automatically from the hardware detected and some profiles.

# Command line

With `engine_module=cmdline`, the content of `engine_module_parameter_base` is passed to
fio, with some limitations. For now, the command line mode has to make sure the fio
benchmark respects the semantic of hwbench: a benchmark lasting exactly `runtime`
seconds, one disk and one stressor count per benchmark, an output hwbench can parse. This
imposes to force some fio keywords: the following ones are automatically defined by
hwbench, and a value given for one of them in `engine_module_parameter_base` is replaced,
with a message.

| Key | Value | Effect |
|---|---|---|
| `--runtime` | the `runtime` of the benchmark | the benchmark lasts exactly `runtime` seconds |
| `--time_based` | enabled | fio runs for the whole `runtime`, even if the I/O pattern ends earlier |
| `--output-format` | `json+` | hwbench parses the JSON output of fio |
| `--name` | the benchmark name | unique over the runs |
| `--numjobs` | the stressor count, from `stressor_range` | a unique value or a list of values, each one giving its own benchmark |
| `--filename` | the disk of the benchmark, from [`disks`](configuration.md#disks) | one benchmark per disk |
| `--invalidate` | `1` | every benchmark runs out of cache |
| `--log_avg_msec` | `20000` | the logs are averaged over 20 seconds, so `runtime` cannot be shorter |
| `--write_bw_log`, `--write_lat_log`, `--write_hist_log`, `--write_iops_log` | `fio/<benchmark>_<type>.log` | hwbench collects the performance logs, for the time-based graphs of hwgraph |

> ℹ️ **Info**
>
> The `runtime` must be at least 20 seconds, the averaging period of the logs: a
> shorter one is rejected with `Fio runtime cannot be lower than the average log time (20000).`

# Metrics

| Key | Value | Effect |
|---|---|---|
| `fio_results` | the JSON output of fio | every metric fio reports for the benchmark: bandwidth, IOPS, latencies… |

The performance logs are kept in the `fio/` directory of the output directory, one file
per type and per benchmark. A skipped benchmark gets an empty `fio_results`, with no job,
and `skipped` set.

# Example

The following job defines two benchmarks on the same device, `/dev/nvme0n1`:
`randread_cmdline_0` with `--numjobs=4`, and `randread_cmdline_1` with `--numjobs=6`,
both taken from the `stressor_range` list.

```ini
[randread_cmdline]
runtime=600
engine=fio
engine_module=cmdline
engine_module_parameter_base=--direct=1 --rw=randread --bs=4k --ioengine=libaio --iodepth=256 --group_reporting --readonly
disks=/dev/nvme0n1
selected_cpus=all
selected_cpus_scaling=none
stressor_range=4,6
```

> ℹ️ **Info**
>
> `selected_cpus` only selects the CPUs fio is pinned on. A possible usage is a list of
> CPU groups with a `selected_cpus_scaling`, to study the performance of the same storage
> device from different NUMA domains.

# Implementation notes

**Files.** The engine is `hwbench/engines/fio.py`, with a single module,
`EngineModuleCmdline`, and `fio` checked as its binary before the run.

**Disks.** `disks` is a mandatory engine specific keyword, declared with
`custom_parameters_required`. `generate_benchmarks()` adds one benchmark per disk to the
expansion; with `disks=all`, it lists the block devices of the target machine, and keeps the
ones that are not mounted and not virtual.

**Command line.** `FioCmdLine.parse_parameters()`, through
`get_default_fio_command_line()`, removes from `engine_module_parameter_base` the options
hwbench enforces, printing the value it replaces, then appends its own; `run_cmd()`
prefixes `fio` with `get_taskset()`.

**Metrics.** `parse_cmd()` loads the JSON output of fio into `fio_results`; an output that
is not valid JSON gives the empty result, like a skipped benchmark.
