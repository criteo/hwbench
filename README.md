# What is hwbench ?
**hwbench** is a benchmark orchestrator to automate the low-level testing of servers.

The documentation is in the [documentation/](./documentation/) directory, see the [Documentation](#documentation) section for the list of the pages.

## What makes hwbench different?
### Scripted language
hwbench embeds a very simplified script language, greatly inspired by [fio](https://github.com/axboe/fio), that turns a very simple script file into a large list of individual tests.
See the [concepts](./documentation/concepts.md) and the [configuration](./documentation/configuration.md) of the job files.

### Prepares the server before the benchmark
Some tuning can be performed automatically to ensure constant system settings across time and reboots. It avoids many human mistakes.

### Collects server's context
At startup, hwbench will collect as much as possible server's context like:
- BIOS configuration
- server properties (via DMI)
- kernel logs
- software versions
- list of hardware components (PCI, CPU, Storage, ...)
- ...

This context will be attached to the performance metrics for later analysis, see [concepts](./documentation/concepts.md#a-result-is-a-measurement-in-a-context).


### Can run any type of benchmark
hwbench is using *engines* to define how to execute a particular external application, see [engines](./documentation/engines.md).
The current version of hwbench supports 5 different engines.
- [stress-ng](https://github.com/ColinIanKing/stress-ng): no need to present this very popular low-level benchmarking tool, see [documentation](./documentation/stressng.md)
- spike: a custom engine used to make fans spike. Very useful to study the cooling strategy of a server, see [documentation](./documentation/spike.md)
- sleep: a stupid sleep call used to observe how the system is behaving in idle mode, see [documentation](./documentation/sleep.md)
- [fio](https://github.com/axboe/fio): a flexible storage benchmarking tool, see [documentation](./documentation/fio.md)
- [pantheon](https://github.com/pantheongpu/pantheon): a vendor agnostic GPU stress and diagnostics suite, see [documentation](./documentation/pantheon.md)

The CPUs a benchmark runs on are selected by the job file, see [CPU selection](./documentation/cpu-selection.md).

Benchmark performance metrics are extracted and saved for later analysis.

### Collects server's environment
If the server is equipped with a [BMC](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface#Baseboard_management_controller),
and only if the monitoring feature is enabled, hwbench will collect environmental metrics and associate them with the final results for later analysis.

This release supports Dell and HPE servers and collects:
- Thermal sensors
- Fans speed
- Power consumption metrics

This feature uses [Redfish](https://www.dmtf.org/standards/redfish) protocol with both generic and OEM-specific endpoints.

If the server is connected to a [PDU](https://en.wikipedia.org/wiki/Power_distribution_unit), and only if the monitoring feature is enabled,
hwbench can collect power metrics from it.

This release supports the following brands:
 - Raritan

hwbench also supports cooling distribution unit (CDU) monitoring through
vendor/model drivers. Each model provides its own readings and
communication driver.

For more details and usage, see the specific [documentation](./documentation/monitoring.md)

# How can results be analyzed?
**hwgraph** tool, bundled in the same repository, generates graphs from **hwbench** output files.
If a single output file is provided, **hwgraph** plots for each benchmark :
- performance metrics
- performance metrics per watt
- environmental metrics along the run:
    - fan speed
    - thermal sensors
    - power consumption
    - CPU frequency

If multiple output files are passed as arguments, and only if they were generated with the same script file, **hwgraph** will compare for each benchmark the performance metrics.

The graphs are described in dedicated pages, with examples:
- [hwgraph](./documentation/hwgraph.md): the command line, the trace files and the options
- [environment graphs](./documentation/hwgraph-environment.md): the monitoring metrics during each benchmark, per host, chassis or group
- [scaling graphs](./documentation/hwgraph-scaling.md): the performance along the scaling steps of a job
- [max versus graphs](./documentation/hwgraph-versus.md): the comparison of the traces, with the reports and the scorecard

---

# Installation

You will first need the following packages on your machine, depending on what you want to run:
1. The "main" tool: `hwbench`; you will install this on your server, or the machine you want to analyse
2. The "graphing" tool: `hwgraph`; this is the part used to parse `hwbench`'s output that will create those nice graphs for you to analyse and compare the runs!
You can install both of them on the server, but `hwgraph` requires some graphics library not always convenient to install in reduced environments.

### Requirements to run hwbench
#### Mandatory
- dmidecode
- lspci
- numactl
- nvme-cli
- python >= 3.12
- turbostat >= 2022.04.16
- util-linux >= 2.32

#### Optional
- AMISCE Utility (for some ODM servers): please contact your hardware vendor to get a copy
- all-smi >= 0.26.0 (for GPU servers, mandatory to load the GPUs, see [installing all-smi](./documentation/monitoring.md#installing-all-smi))
- ilorest (for HPE servers)
- ipmitool
- pantheon >= 1.2.0 (for GPU servers)
- rpm or dpkg-query (apt), to list the installed packages
- stress-ng >= 0.17.04

### Requirements to run hwgraph
#### Mandatory
- python >= 3.12
- Headers for Cairo (`cairo-devel` on RHEL-based or `libcairo2-dev` for Debian-based)
- Python 3 headers for your current interpreter (`python3-devel` on RHEL-based or `python3-dev` for Debian-based)


## Actual installation
We do not (yet, coming at some point) provide a PyPi package. However, installation is almost just as simple:
1. Clone the repository
2. Make sure that you have all the requirements above already installed on your system. If you're missing a recent version of Python, `uv` will help you with this
3. Install a recent version of `uv` on your system: we require a version above 0.4.27, so you can just do a `pip install uv` on your system to install the latest release. If you are on Ubuntu or another Debian-derivative, you may receive an error and need to follow the guide on [uv's official website](https://docs.astral.sh/uv/getting-started/installation/).
4. Run `uv sync` in the repository. If you did not have a recent enough version of Python, you can add `-p <insert wanted version>` to the command.
> [!WARNING]
> If you want to also include the dependencies for the plotting, run `uv sync --extra graph` instead!
5. Have fun running `uv run hwbench` (as root) and `uv run hwgraph`!

---

# Examples
Running the **curve-cpu.conf** job:
<code>python3 -m hwbench.hwbench -j configs/curve-cpu.conf -e environment.cfg</code>

The sample job files are in [configs/](./configs/), each of them starting with the intention it measures.

Graphing the results of two runs, see [hwgraph](./documentation/hwgraph.md#rendering-the-graphs-graph):
<code>uv run hwgraph graph --traces documentation/example/traces/baseline.json:baseline:BMC.Server documentation/example/traces/hpc.json:hpc:BMC.Server --outdir graphs</code>

The graphs of the documentation are rendered from a [reference dataset](./documentation/example/README.md).

---

# Documentation
All the pages are in the [documentation/](./documentation/) directory.

| Page | Content |
|---|---|
| [concepts.md](./documentation/concepts.md) | the concepts and the vocabulary: job, benchmark, context |
| [configuration.md](./documentation/configuration.md) | the reference of the job file keywords |
| [cpu-selection.md](./documentation/cpu-selection.md) | how a job selects the CPUs to load |
| [engines.md](./documentation/engines.md) | the engine model, with [stressng.md](./documentation/stressng.md), [fio.md](./documentation/fio.md), [pantheon.md](./documentation/pantheon.md), [spike.md](./documentation/spike.md) and [sleep.md](./documentation/sleep.md) |
| [monitoring.md](./documentation/monitoring.md) | the BMC, the PDU, turbostat and all-smi metrics, and the environment file |
| [topology.md](./documentation/topology.md) | the topology file locating the servers of a fleet, its validator, and how to write an exporter |
| [hwgraph.md](./documentation/hwgraph.md) | the graphs and the comparison of the results, with [hwgraph-environment.md](./documentation/hwgraph-environment.md), [hwgraph-scaling.md](./documentation/hwgraph-scaling.md) and [hwgraph-versus.md](./documentation/hwgraph-versus.md) |
