# What is hwbench ?
**hwbench** is a benchmark orchestrator to automate the low-level testing of servers.

## What makes hwbench different?
### Scripted language
hwbench embeds a very simplified script language, greatly inspired by [fio](https://github.com/axboe/fio), that turns a very simple script file into a large list of individual tests.

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

This context will be attached to the performance metrics for later analysis.


### Can run any type of benchmark
hwbench is using *engines* to define how to execute a particular external application.
The current version of hwbench supports 3 different engines.
- [stress-ng](https://github.com/ColinIanKing/stress-ng): no need to present this very popular low-level benchmarking tool
- spike: a custom engine used to make fans spike. Very useful to study the cooling strategy of a server.
- sleep: a stupid sleep call used to observe how the system is behaving in idle mode
- [fio](https://github.com/axboe/fio): a flexible storage benchmarking tool, see [documentation](./documentation/fio.md)

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

For more details, see the specific documentation.

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
- rpm
- turbostat >= 2022.04.16
- util-linux >= 2.32

#### Optional
- AMISCE Utility (for some ODM servers): please contact your hardware vendor to get a copy
- ilorest (for HPE servers)
- ipmitool
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
Running the **simple.conf** job:
<code>python3 -m hwbench.hwbench -j configs/simple.conf -m monitoring.cfg</code>
