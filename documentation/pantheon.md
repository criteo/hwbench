# pantheon: accelerator benchmarking

The `pantheon` engine drives [pantheon](https://github.com/pantheongpu/pantheon), a vendor
agnostic GPU stress and diagnostics suite: it builds its own CUDA or HIP kernels and runs one of
its 49 workloads on the selected accelerators, reporting per GPU the achieved throughput, the
temperature and power ranges, the clocks, the time spent throttled and the RAS counters. It is
the accelerator counterpart of what `stressng` does on the CPU cores.

- [Requirements](#requirements)
- [Concept](#concept)
- [Sample configuration file](#sample-configuration-file)
- [Results](#results)
- [Graphing](#graphing)
- [Implementation notes](#implementation-notes)

Related pages: [engines](./engines.md), [configuration](./configuration.md),
[monitoring](./monitoring.md).

# Requirements

- `pantheon` >= 1.2.0, i.e. `pip install pantheon-gpu`, or the `apt`, COPR or Docker packages.
  Older releases have neither the json report nor the `--gpu` selector hwbench relies on, so an
  older binary stops hwbench before running anything, with the other missing requirements:
  `CRITICAL:root:Requirements are not met: Binary pantheon 1.1.0 is too old, expecting >= 1.2.0`.
- A CUDA or ROCm toolchain: pantheon compiles its kernels on first use and needs `nvcc` or
  `hipcc` for that, not only the driver. hwbench compiles them itself before the first
  benchmark starts, so the compilation never lands inside a monitored window: left to the first
  run, it would report the accelerators idling while the compiler works. That warm up runs the
  `baseline_metrics` workload for a second, which measures an idle accelerator, so the
  accelerators still start the first benchmark cold. It is a no-op once the cache is warm.
- `all-smi` >= 0.26.0, which finds the accelerators: their inventory, the indexes
  [`selected_gpus`](./configuration.md#selected_gpus) selects on, and their monitoring during
  the run. A job file with a `pantheon` job stops before running anything, with the other
  missing requirements, when all-smi is missing, older or reports no accelerator. See
  [Installing all-smi](./monitoring.md#installing-all-smi).

## Kernel cache

pantheon caches the compiled kernels under `$XDG_CACHE_HOME/pantheongpu/builds/<version>/`,
`~/.cache` when `XDG_CACHE_HOME` is unset, in one directory per platform and accelerator
architecture: `builds/1.2.2/cuda-100` for CUDA on an NVIDIA B200 (`sm_100`).

The key is the version pantheon reports, not its source: a development checkout reporting the
same version as a release reuses the kernels of that release. Move the version directory aside
before switching between the two, so the warm up compiles the new kernels.

## Running an unreleased pantheon

A fix only on the pantheon `main` branch is not in the `pantheon-gpu` package. The checkout has
no Python packaging, so it cannot be installed with `pip`: it runs as `python pantheon.py`.
hwbench runs the `pantheon` binary found in the `PATH`, so a wrapper replaces it:

```sh
git clone https://github.com/pantheongpu/pantheon /opt/pantheon
pip install -r /opt/pantheon/requirements.txt
printf '#!/bin/sh\nexec python3 /opt/pantheon/pantheon.py "$@"\n' > /usr/local/bin/pantheon
chmod +x /usr/local/bin/pantheon
```

The checkout reports its version as `pantheon.py 1.2.2`; hwbench reads the last field, so the
version check applies as with a release.

> ℹ️ **Info**
>
> The power stress fixes of `omni_virus` and of the arithmetic tests (pantheon #26 and #28) were
> merged on `main` after `pantheon-gpu` 1.2.2, the latest release. Use a checkout of `main` to
> burn the accelerators with `omni_virus`, see [Power draw of the workloads](#power-draw-of-the-workloads).

# Concept

An `engine_module` is one of the pantheon suites and an `engine_module_parameter` one of its
workloads:

| `engine_module` | Workloads |
|---|---|
| `baseline` | `baseline_metrics` |
| `core` | `voltage`, `incinerator`, `fp64_virus`, `int_virus`, `mma_virus`, `sfu_stress`, `pulse_virus`, `tensor_virus`, `transformer_virus`, `omni_virus` |
| `memory` | `memory_thermal_asym`, `memory_cache_fracture`, `memory_retention_bake`, `memory_retention`, `memory_bank_thrash`, `memory_write`, `memory_write_agg`, `memory_read`, `memory_read_agg`, `cache_lat`, `atomic_virus` |
| `interconnect` | `tlb_avalanche`, `scheduler`, `pcie_bandwidth`, `p2p_thrasher`, `all_reduce`, `memory_pc_pingpong`, `memory_tsv_thrasher` |
| `diagnostics` | `march_test`, `galpat`, `memory_hammer`, `memory_retention`, `ras_validator` |
| `fixedFunction` | `rt_virus`, `media_enc_virus` |
| `inference` | `llm_decode`, `llm_prefill`, `kv_cache_churn`, `fused_attention`, `rope_stress`, `quantized_gemm`, `serving_mix`, `speculative_decode`, `moe_router` |
| `training` | `transformer_train_step` |
| `runtime` | `allocation_fragmentation`, `graph_replay` |
| `ai_auxiliary` | `rag_embedding`, `vision_encoder` |

`engine_module_parameter` has no usable default here, so it must be set. Listing several values
(`tensor_virus,fp64_virus,int_virus`), or `all` to take every workload of the suite, generates
one benchmark per workload: the datapaths of an accelerator have very different power envelopes
for the same occupancy, which makes this a cheap way to study the power behaviour of a server.

One hwbench benchmark always runs exactly one pantheon workload, so `runtime` is the duration of
that workload. pantheon then cools the accelerators down for a tenth of it, capped at a minute,
which is not part of the monitored window.

## Power draw of the workloads

The power viruses of the `core` suite do not all reach the power limit of an accelerator. On a
server with 8 NVIDIA B200, a 1000 W power limit each, every accelerator loaded at once for
180 seconds, the board power read by `nvidia-smi` was:

| Workload | `pantheon-gpu` 1.2.2 | pantheon `main` (`3c534ca`) |
|---|---|---|
| idle | ~240 W | ~240 W |
| `incinerator` | ~450 W | ~400 W |
| `tensor_virus` | ~440 W | ~440 W |
| `omni_virus` | not measured | 860 to 966 W, held at the power limit |
| `voltage` | not measured | ~515 W |
| `pulse_virus` | not measured | ~285 W on average, it alternates load and idle |

Only `omni_virus` throttled, on its software power cap, the clock dropping as low as 1095 MHz
from 1965 MHz; every other workload kept the full clock. It is therefore the workload that
checks whether the cooling and the power delivery sustain the accelerators at their limit.

## Selecting and scaling the accelerators

[`selected_gpus`](./configuration.md#selected_gpus) selects the accelerators a job loads and
[`selected_gpus_scaling`](./configuration.md#selected_gpus_scaling) how many benchmarks they
give, the accelerator equivalent of `selected_cpus` and `selected_cpus_scaling`. By default,
`all` and `none`: a single benchmark loading every accelerator.

Each benchmark runs one pantheon process, given its GPUs with `--gpu`, and counts one stressor
per GPU. The accelerators it loaded are recorded in its results under `gpu_pin`, and `hwgraph`
uses their count as the X axis of the scaling graphs. The start line of a benchmark names them:

```
[gpu_count_scaling_1] pantheon/core/tensor_virus(M):   2 stressor on GPU [0-1] for 300s
```

[`uv run hwbench -j <job_file> --dry-run`](cpu-selection.md#previewing-a-job-file---dry-run)
draws, for a job loading the GPUs, one column per accelerator instead of the CPU map:

```
gpu                     01234567  stressors  engine/module/parameter              gpus
gpu_count_scaling_0     #.......          1  pantheon/core/tensor_virus           0
gpu_count_scaling_1     ##......          2  pantheon/core/tensor_virus           0-1
```

## Other directives

[`gpu_memory_percent`](./configuration.md#gpu_memory_percent) sets the share of the free VRAM
a workload allocates, [`verify`](./configuration.md#verify) the silent data corruption check
run after it, and [`platform`](./configuration.md#platform) forces the compiler backend.

`platform=mock` makes pantheon build and run a CPU kernel against one fake accelerator. It
measures nothing about the hardware, but it is a way to exercise a job file, the result parsing
and the graphs on a machine without any GPU.

Note that pantheon is deliberately not pinned with `taskset`: the load is on the accelerators,
and constraining the feeding threads would only distort the measurement. `selected_cpus` is
therefore irrelevant for this engine.

## Numbering

`selected_gpus` selects on the index of the hwbench inventory, which is the order `all-smi` enumerated the
accelerators in, and which is also what the `GPU_<n>` monitoring metrics are named after. That
index is passed to pantheon as `--gpu`, and pantheon enumerates the accelerators itself.

On a server whose accelerators all come from the same vendor, both enumerations follow the driver
order and agree. hwbench does not assume it: it compares the UUIDs pantheon reports against the
inventory and prints a warning naming the two if they disagree, because the monitoring of the
benchmark could then not be matched to its results.

# Sample configuration file

`configs/gpu.conf` loads every accelerator of the server at once, after five monitored idle
minutes used as the thermal and power baseline:

```ini
[global]
runtime=900
monitor=all

[cool_down]
engine=sleep
runtime=300

[burn_all_gpus]
engine=pantheon
engine_module=core
engine_module_parameter=tensor_virus
selected_gpus=all
selected_gpus_scaling=none
```

`selected_gpus` and `selected_gpus_scaling` are written although they hold their defaults: they
say what the job loads. One benchmark loads every accelerator. `tensor_virus` runs with any
pantheon release, but does not reach the power limit of the accelerators, see
[Power draw of the workloads](#power-draw-of-the-workloads).

`configs/gpu_scaling.conf` varies the load instead. Its `gpu_count_scaling` job,
`selected_gpus_scaling=curve` on an 8 GPUs server, creates five benchmarks:

- `gpu_count_scaling_0` loading GPU 0
- `gpu_count_scaling_1` loading GPU 0 and 1
- `gpu_count_scaling_2` loading GPU 0 to 2
- `gpu_count_scaling_3` loading GPU 0 to 3
- `gpu_count_scaling_4` loading GPU 0 to 7

Its `per_gpu_health` job runs `omni_virus` on one accelerator at a time, so a card that cannot
sustain the power limit as its peers do stands out.

`configs/full_gpu_load.conf` is the soak variant, the accelerator counterpart of
`configs/full_cpu_load.conf`: after the same idle baseline, it runs back to back, six minutes each
and on every accelerator at once, the five power viruses of the `core` suite and the two `memory`
workloads that bake the HBM stacks. About 50 minutes in total, plus the kernel build. It measures
nothing the other two do not, its point is to sustain the power and thermal limits long enough for
the cooling to react and for the throttling to show up, which makes it a validation run rather
than a measurement one. Of its workloads, only `omni_virus` from pantheon `main` holds the
accelerators at their power limit.

# Results

pantheon does not report on its standard output: it writes a json report per run and logs where.
hwbench runs it in the output directory of the benchmark, follows that log line and reports,
under `pantheon_results`:

- `suite` and `test`, what was run, plus the `version` of pantheon and the `toolkit_version` of
  the CUDA or ROCm toolchain it built with
- `healthy` and `exit_code`: pantheon exits 1 when a workload failed or an accelerator
  misbehaved. hwbench records that verdict and keeps the full results, it is not treated as a
  failure.
- one entry per accelerator under `gpus`, keyed by the index, with its `name`, `uuid`,
  `manufacturer` and `status`, its `score` and `unit`, the `temperature`, `power`, `clock`,
  `utilization` and `memory` figures pantheon measured, its `energy_wh`, `thermal_rise_celsius`,
  `throttle_seconds` and `throttle_reason`, its `pcie_gen`/`pcie_width`, and its `ras_status`.
  A quantity the accelerator exposes no sensor for is reported as `null` rather than as a zero.
  A workload that failed also carries its `failure_stage` and `failure_reason`.

Three aggregates sit next to it: `score`, the sum over every loaded accelerator, which is the
metric `hwgraph` plots, `score_min_gpu`, the worst accelerator of the run, and `score_unit`,
because the pantheon workloads do not all measure the same thing: the compute ones report TFLOPS
and the memory ones GB/s.

pantheon also leaves its own output in the benchmark directory: `results/<run>/summary.csv` for
the same rows in a spreadsheet, `results/<run>/time_series.csv` for its per sample telemetry, and
`database/` for the json reports.

# Graphing

`hwgraph` still requires the power metric of its `--traces <trace_filename>:<logical_name>:<power_metric>`
argument to exist, so a GPU trace must be collected with `monitor=all`. Use `hwgraph list
--trace <trace_filename>` to see the available ones: `BMC.Server` is the usual choice, and
`GPU.GPU_0` is also valid once the all-smi monitoring is active.

The header of every graph describes the accelerators of the server next to its CPU, and
`benchmarks_summary.txt` lists them with the system, with where each GPU sits (see
[GPU locator](./monitoring.md#gpu-locator)), then gives the GPUs each benchmark loaded in a
`GPUs` column. What all the accelerators share fits on one line; a property differing
between them, like a VBIOS, gets one line per value naming the GPUs that have it:

```
GPU: 8x NVIDIA B200, Driver: 610.57.04, CUDA: 13.3, ECC: enabled
GPU 0-3: VBIOS: 97.00.FA.00.02
GPU 4-7: VBIOS: 97.00.FA.00.01
```

The performance metric plotted is `score`, the sum over the loaded accelerators, so it scales
with the GPU count of each step, and its axis is labelled with the unit of the workload. The X
axis of the scaling graphs is that GPU count.

Per-GPU metrics are rendered twice, the same way the CPU ones are rendered for all cores and for
the pinned cores: once over every accelerator of the server, once restricted to the ones the
benchmark actually used (`used_gpus`). The restricted view is the useful one on a scaling job,
where the idle accelerators would otherwise dominate the distribution. It only covers the all-smi
metrics, since Redfish ids cannot be mapped to accelerator indexes.

Comparing two traces with `hwgraph versus` skips the pantheon results themselves, since they are
what differs between two servers running the same job, and reports the performance per
accelerator rather than per core.

The traces comparison written to `max_versus/benchmarks_summary.txt` (and, per scaling step, to
`scaling/summary/`) follows the same rule. When every benchmark loads the GPUs, it describes the
accelerators of each trace instead of its CPU, and drops the CPU columns (`Perf/core`, `IPC`,
`CoV`): `GPUs` is the number of GPUs loaded, `Perf/GPU` the performance per GPU loaded, `Clock`
the mean clock of those GPUs and `Temp` their mean temperature. The host CPU, which feeds the
GPUs, gets a second table under each benchmark: its mean package power (`n/a` when the trace
holds no `CPU.package`), core clock and IPC. A report mixing CPU and GPU
benchmarks keeps the CPU columns, names the normalized one `Perf/unit` (per physical core for a
CPU benchmark, per GPU loaded for a GPU one) and adds `Temp`.

The BMC of a GPU server exposes many sensors, and some of them miss a sample now and then.
`hwgraph` then stops on that sensor, for example:

```
Fatal: <trace>/<benchmark>: second axis of <sensor>: <sensor> is missing the 9th data point.         Use --ignore-missing-datapoint to ignore this case. Generated graphs will be partially incorrect.
```

`--ignore-missing-datapoint last` repeats the previous value of that sensor instead, and
`--ignore-missing-datapoint zero` records a zero; only the curves of that sensor are approximated.

# Implementation notes

- `hwbench/engines/pantheon.py`:
  - `SUITES` lists the workloads of each suite.
  - `Engine` declares `resources = (Resource.GPU,)` and `min_version`, the oldest supported
    release, validates the engine specific directives and reads the version
    (`parse_version`).
  - `EngineModuleSuite.generate_benchmarks` forwards the engine specific directives to every
    benchmark; `warmup` calls `build_kernels` once per platform.
  - `Pantheon` builds the command line (`run_cmd`), follows the report line (`load_report`) and
    turns the report into `pantheon_results` (`parse_cmd`, `build_gpus`, `check_identities`).
- `hwbench/config/config.py`: `Config.get_selected_gpus` resolves `selected_gpus` against the
  detected accelerators.
- `hwbench/bench/benchmarks.py`: `Benchmarks.parse_jobs_config` expands it with
  `selected_gpus_scaling`, through the `scaling()` function of `hwbench/bench/scaling.py`, into
  the `pinned_gpus` of each `BenchmarkParameters`.
- `hwbench/environment/all_smi.py`: `list_gpus` is the accelerator inventory `selected_gpus`
  indexes, and `check_requirements` what a job loading the GPUs requires.
