# pantheon

hwbench can use [pantheon](https://github.com/pantheongpu/pantheon) to stress accelerators.

pantheon is a vendor agnostic GPU stress and diagnostics suite: it builds its own CUDA or HIP
kernels and runs one of its 49 workloads on the selected accelerators, reporting per GPU the
achieved throughput, the temperature and power ranges, the clocks, the time spent throttled and
the RAS counters. It is the accelerator counterpart of what `stressng` does on the CPU cores.

# Requirements

- `pantheon` >= 1.2.0, i.e. `pip install pantheon-gpu`, or the `apt`, COPR or Docker packages.
  Older releases have neither the json report nor the `--gpu` selector hwbench relies on; a
  benchmark using an older binary is skipped, honouring the `skip_method` directive.
- A CUDA or ROCm toolchain: pantheon compiles its kernels on first use and needs `nvcc` or
  `hipcc` for that, not only the driver. The build is cached under
  `$XDG_CACHE_HOME/pantheongpu/builds`. hwbench compiles them itself before the first
  benchmark starts, so the compilation never lands inside a monitored window: left to the first
  run, it would report the accelerators idling while the compiler works. That warm up runs the
  `baseline_metrics` workload for a second, which measures an idle accelerator, so the
  accelerators still start the first benchmark cold. It is a no-op once the cache is warm.
- `all-smi`, used to enumerate the accelerators and to collect their power, frequency,
  utilization, memory and temperature during the run. It is optional for hwbench as a whole, but
  the `pantheon` engine cannot expand `gpus=all` without it. See
  [monitoring](./monitoring.md#all-smi).

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

`tensor_virus` is the closest equivalent of a classic GPU burn-in: it is the workload that draws
the most power on a datacenter card.

One hwbench benchmark always runs exactly one pantheon workload, so `runtime` is the duration of
that workload. pantheon then cools the accelerators down for a tenth of it, capped at a minute,
which is not part of the monitored window.

## Selecting and scaling the accelerators

Two engine specific directives drive which accelerators are loaded. They are the accelerator
equivalent of `selected_cpus` and `selected_cpus_scaling`.

`gpus` defines the pool of eligible accelerators, using the index of the hwbench inventory
(see [Numbering](#numbering)):

| Value | Meaning |
|---|---|
| `all` | Every detected accelerator (default) |
| `0,3` | GPU 0 and GPU 3 |
| `0-7` | GPU 0 to GPU 7 |
| `0 0,1 0-3` | Three groups of GPUs, consumed by `gpu_scaling=iterate` |

`gpu_scaling` defines how that pool is consumed:

| Value | Meaning |
|---|---|
| `none` | A single benchmark loading the whole pool (default) |
| `iterate` | One benchmark per group, or one benchmark per GPU when the pool is a flat list |
| `plus_<x>` | A cumulative ladder adding `<x>` GPUs at each step |
| `simple` | A cumulative ladder of 1, 2, 4, 8 ... GPUs, up to the size of the pool |

The accelerators actually loaded by a benchmark are recorded in its results under
`custom_parameters.gpu_list`, and `hwgraph` uses their count as the X axis of the scaling graphs.

## Other directives

| Directive | Default | Meaning |
|---|---|---|
| `gpu_memory_percent` | `99` | Percentage of the free VRAM the workload allocates, 1 to 99 |
| `verify` | `true` | Run the silent data corruption check after the workload |
| `platform` | unset | Force the compiler backend: `auto`, `cuda`, `hip`, or `mock` |

`platform=mock` makes pantheon build and run a CPU kernel against one fake accelerator. It
measures nothing about the hardware, but it is a way to exercise a job file, the result parsing
and the graphs on a machine without any GPU.

Note that pantheon is deliberately not pinned with `taskset`: the load is on the accelerators,
and constraining the feeding threads would only distort the measurement. `selected_cpus` is
therefore irrelevant for this engine.

## Numbering

`gpus` selects on the index of the hwbench inventory, which is the order `all-smi` enumerated the
accelerators in, and which is also what the `GPU_<n>` monitoring metrics are named after. That
index is passed to pantheon as `--gpu`, and pantheon enumerates the accelerators itself.

On a server whose accelerators all come from the same vendor, both enumerations follow the driver
order and agree. hwbench does not assume it: it compares the UUIDs pantheon reports against the
inventory and prints a warning naming the two if they disagree, because the monitoring of the
benchmark could then not be matched to its results.

# Sample configuration file

`configs/gpu.conf` loads every accelerator of the server at once, after five monitored idle
minutes used as the thermal and power baseline:

```
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
gpus=all
gpu_scaling=none
```

`configs/gpu_scaling.conf` varies the load instead. Its `gpu_count_scaling` job, on an
8 GPUs server, creates four benchmarks:

- `gpu_count_scaling_0` loading GPU 0
- `gpu_count_scaling_1` loading GPU 0 and 1
- `gpu_count_scaling_2` loading GPU 0 to 3
- `gpu_count_scaling_3` loading GPU 0 to 7

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

`hwgraph` still requires the power metric of its `--traces <file>:<name>:<power_metric>`
argument to exist, so a GPU trace must be collected with `monitor=all` on a server whose BMC or
CPU power is readable. `PowerConsumption.GPU.GPU_0` is also a valid choice once the all-smi
monitoring is active.
