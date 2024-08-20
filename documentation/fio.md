# FIO

hwbench can use [fio](https://github.com/axboe/fio) to perform storage benchmarking.
The current implementation requires fio >= 3.19.

# Concept
Fio is operated in three(3) different modes by selecting the `engine_module` directive.

## Command line

When `engine_module=cmdline` is used, the content of `engine_module_parameter_base` will be passed directly to fio with some limitations.

The following fio keywords are automatically defined, or replaced if present, by hwbench :

- `--runtime`: set to match the exact duration of the current hwbench benchmark.
- `--time_based`: it's mandatory to have a benchmark lasting `runtime` seconds.
- `--output-format`: hwbench need the output to be set in `json+` for an easy integration.
- `--name`: hwbench will use the current job name to ensure its unique over the runs.
- `--numjobs`: defined by `stressor_range`, can be set as a unique value or a list of values. Each value will generate a new benchmark.
- `--write_{bw|lat|hist|iops}_logs`: hwbench will automatically collect the performance logs to let hwgraph doing time-based graphs.
- `--invalidate`: hwbench ensure that every benchmark will be done out of cache.

### Sample configuration file

The following job defines two benchmarks on the same device (nvme0n1).

The `randread_cmdline` job will create :
- `randread_cmdline_0` benchmark with ``numjobs=4`` extracted from `stressor_range` list
- `randread_cmdline_1` benchmark with ``numjobs=6`` extracted from `stressor_range` list

```
[randread_cmdline]
runtime=600
engine=fio
engine_module=cmdline
engine_module_parameter_base=--filename=/dev/nvme0n1 --direct=1 --rw=randread --bs=4k --ioengine=libaio --iodepth=256 --group_reporting --readonly
hosting_cpu_cores=all
hosting_cpu_cores_scaling=none
stressor_range=4,6
```

Please note the `hosting_cpu_cores` only selects a set of cores to pin fio. A possible usage would be using a list of cores with a `hosting_cpu_cores_scaling` to study the performance of the same storage device from different NUMA domains.

## External file execution
Hwbench execute an already existing fio job file.

Not yet implemented.

## Automatic job definition
Hwbench automatically creates jobs based on some hardware detection and profiles.

Not yet implemented.
