# What is hwbench ?
**hwbench** is a benchmark orchestrator to automate the low-level testing of servers.

## What makes hwbench different?
### Scripted language
hwbench embeds a very simplified script language, greatly inspired by [fio](https://github.com/axboe/fio), that turns a very simple script file into a large list of individual tests.

### Preparing the server before the benchmark
Some tuning can be performed automatically to ensure constant system settings across time and reboots. It avoids many human mistakes.

### Collect server's context
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
[stress-ng](https://github.com/ColinIanKing/stress-ng): no need to present this very popular low-level benchmarking tool
- spike: a custom engine used to make fans spiking. Very useful to study the cooling strategy of a server.
- sleep: a stupid sleep call used to observe how the system is behaving in idle mode

Benchmark performance metrics are extracted and saved for later analysis.

### Collect server's environment
If the server is equipped with a [BMC](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface#Baseboard_management_controller), hwbench will collect environmental metrics and associate them with the final results for later analysis.

This release supports Dell and HPE servers and collects:
- Thermal sensors
- Fans speed
- Power consumption metrics

This feature uses [redfish](https://www.dmtf.org/standards/redfish) protocol with both generic and OEM-specific endpoints.

For more details and usage, see the specific documentation.

# How can results be analyzed?
**hwgraph** tool, bundled in the same repository, generates graphs from **hwbench** output files.
If a single output file is provided, **hwgraph** plot for each benchmark :
- performance metrics
- performance metrics per watt
- environmental metrics along the run:
    - fan speed
    - thermal sensors
    - power consumption
    - CPU frequency

If multiple output files are passed in argument, and only if they were generated with the same script file, **hwgraph** will compare for each benchmark the performance metrics.

For more details, see the specific documentation.