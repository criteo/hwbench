# hwgraph environment graphs: the target machine during each benchmark

The environment graphs plot what the monitoring collected **during** each benchmark: the
power, the frequencies, the IPC, the fans and the temperatures of the target machine. They
are rendered for every benchmark of every trace, unless `--no-env` is given.

- [Per host](#per-host)
  - [CDU and host comparison](#cdu-and-host-comparison)
  - [Per-core views](#per-core-views)
  - [Reading a violin](#reading-a-violin)
  - [Per NUMA domain](#per-numa-domain)
  - [Benchmarks summary](#benchmarks-summary)
- [Per chassis](#per-chassis)
- [Per group](#per-group)
  - [Groups of the location](#groups-of-the-location)

Related pages: [hwgraph.md](hwgraph.md) (the command line, the traces and the output tree),
[monitoring.md](monitoring.md) (where the metrics come from), [cpu-selection.md](cpu-selection.md)
(the pinned cores), [hwgraph-scaling.md](hwgraph-scaling.md) and
[hwgraph-versus.md](hwgraph-versus.md) (the performance graphs).

# Per host
For each trace, and for each benchmark of the trace, hwgraph writes
`environment/by_host/<logical_name>/<benchmark>/<metric>/`, where `<benchmark>` is the name
in the results, like `cpu_3`, and `<metric>` the kind of metric:

| Directory | Graphs | What they plot |
|---|---|---|
| `Thermal` | `Thermal` | the temperature sensors of the BMC |
| `Fans` | `<fan>`, `Fans speed_vs_Thermal`, `Fans speed_vs_PowerConsumption` | one graph per fan, with the minimum and maximum of each aggregation; and the speed of all the fans, with the temperatures or the power on a second axis |
| `PowerConsumption` | `Package power consumption`, `PDU power reporting` | the power of the CPU package, and of the [PDU](monitoring.md#pdu) outlets |
| `PowerConsumption/all_cores` | `CPU Core power consumption` | the power of every core |
| `Freq/all_cores` | `Core frequency` | the frequency of every core |
| `IPC/all_cores` | `Core IPC` | the instructions per cycle of every core |
| `Monitor` | `Polling` | the time spent by the monitoring to poll its sources |
| `CDU/<index>-<section>` | `CDU and host temperatures_vs_PowerConsumption` | CDU circuit, CPU and GPU temperatures in °C, with CPU package power, the selected trace power metric and the GPU power in watts on the second axis |

The graphs of this page are rendered from the [reference dataset](example/README.md): the benchmark `cpu_17`, 36 stressors of `stressng cpu int128` during 120 seconds, on a server with 32 physical cores and 8 NUMA domains.

![Thermal](img/hwgraph-env-thermal.png)

*`Thermal/Thermal.png`: the temperature sensors of the BMC during the benchmark.*

![Fans speed vs Thermal](img/hwgraph-env-fans-vs-thermal.png)

*`Fans/Fans speed_vs_Thermal.png`: the speed of the fans, with the temperatures on the second axis.*

![Package power consumption vs Thermal](img/hwgraph-env-package-power-vs-thermal.png)

*`PowerConsumption/Package power consumption_vs_Thermal.png`: the power of the CPU package, with the temperatures on the second axis.*

The power, frequency and IPC graphs of the CPU and of the PDU exist in several variants:

| Variant | Effect |
|---|---|
| `<graph>` | the metric alone |
| `<graph>_vs_Thermal` | the metric, with the temperature sensors on a second axis, the ones of the CDUs included, a window without CDU reading being a gap |
| `<graph>_vs_PowerConsumption` | the metric, with the power consumption metrics, and the power supplies, on a second axis |

> ℹ️ **Info**
>
> The `Polling` graphs of the BMC, the PDU and the CPU monitoring share the same file
> name: only one of them remains in `Monitor`.

Each host also gets:

| File | Content |
|---|---|
| `NUMA distances` | the distance matrix between the NUMA domains of the host, with the cores of each domain; needs the matrix of at least two domains |
| `benchmarks_summary.txt` | the [benchmarks summary](#benchmarks-summary) |

![NUMA distances](img/hwgraph-env-numa-distances.png)

*`NUMA distances.png`: the distance between the NUMA domains of the host, which domains are close to each other, and which are far.*

## CDU and host comparison

For each configured CDU, hwgraph automatically generates
`CDU/<index>-<section>/CDU and host temperatures_vs_PowerConsumption.png` (with `--format png`), named as the
other graphs with a second axis, `<graph>_vs_<context of the second axis>`.
The left axis shows the primary/secondary supply and return temperatures, the
CPU temperature sensors, and the temperatures of the GPUs when the run has some. The
right axis shows `CPU.package` power, when available, the power metric selected by
`--traces`, such as `BMC.Server`, and the power of each GPU. Power curves are
dashed. Beyond 10 curves, they take the 20 colors of the `tab20` palette. Every curve uses the same aggregation grid, with gaps for missing readings.

CDU graph legends summarize the **window means shown on the curves**, excluding
empty windows. Each valid window has equal weight regardless of its number of
readings. These min/mean/stddev/max values are not statistics of all raw readings;
for example, a one-reading window weighs as much as a complete window.

The comparison requires at least one CDU circuit temperature, a CPU temperature
sensor and a power metric. CDU profiles expose circuit temperatures with the
optional semantic keys `primary_supply_temperature`, `primary_return_temperature`,
`secondary_supply_temperature` and `secondary_return_temperature`, in `Celsius`.
This selection is independent of vendor, model, OIDs and display labels. Other CDU
readings remain available in the per-unit graphs.

![CDU and host temperatures with power](img/hwgraph-env-cdu-comparison.png)

*Recorded host monitoring from `numa.json`, with synthetic CDU temperatures for
illustration. The empty window demonstrates a failed CDU reading.*

## Per-core views
The per-core metrics (`Core frequency`, `Core IPC`, `CPU Core power consumption`) are
rendered once per view, each in its own subdirectory of the metric:

| Subdirectory | View | Exists |
|---|---|---|
| `all_cores` | every core of the target machine, one line per core | always |
| `pinned_cores` | only the cores the benchmark was [pinned](cpu-selection.md) to; the title says `View limited to the pinned logical cores [0-7, 64-71]` | for a benchmark that pinned cores |
| `all_numa` | the cores of each NUMA domain aggregated, one line per domain | when the trace has the NUMA topology |
| `pinned_numa` | the same, for the NUMA domains of the pinned cores | when the trace has the NUMA topology and the benchmark pinned cores |

A trace without the topology prints `no NUMA metric present in trace file, skipping`.

The `all_*` views observe the **whole machine**, including the cores the benchmark did not
use: they show what the idle cores do while the others are loaded. The `pinned_*` views focus
on the cores the benchmark ran on, so the idle cores do not "pollute" the graph: their low
frequency or IPC would otherwise drag down the lines, the averages and the distributions.

The graphs of each view:

| Graph | Views | What it plots |
|---|---|---|
| `<metric>` | `all_cores`, `pinned_cores` | one line per core over the time |
| `<metric>_vs_Thermal`, `<metric>_vs_PowerConsumption` | `all_cores`, `pinned_cores` | the same, with the temperature sensors, or the power metrics and the power supplies, on a second axis |
| `<metric> - distribution` | `all_cores`, `pinned_cores` | the distribution of the cores during the benchmark, as a violin and a box plot |
| `<metric> per NUMA domain` | `all_numa`, `pinned_numa` | one line per NUMA domain over the time: `Core frequency per NUMA domain`, `Core IPC per NUMA domain`, `CPU Core power consumption per NUMA domain` |
| `<metric> per NUMA domain - distribution` | `all_numa`, `pinned_numa` | the distribution of each NUMA domain, as a violin |
| `<metric> per NUMA domain - heatmap` | `all_numa`, `pinned_numa` | the NUMA domains over the time, colored by value; for the frequency and the IPC only |

![Core frequency, all cores](img/hwgraph-env-freq-all-cores.png)

*`Freq/all_cores/Core frequency.png`: all the cores of the server. The cores used by the benchmark run at their top frequency, the others at lower and different ones.*

![Core frequency, pinned cores](img/hwgraph-env-freq-pinned-cores.png)

*`Freq/pinned_cores/Core frequency.png`: the same benchmark, limited to the pinned cores, named in the title.*

## Reading a violin
![Core frequency distribution](img/hwgraph-env-freq-distribution.png)

*`Freq/all_cores/Core frequency - distribution.png`: the distribution of the frequency of the cores during the benchmark.*

The `- distribution` graphs are **violin plots**: they show the **distribution of the individual results**, here one
result per core, its mean over the benchmark, instead of a single average that would hide the differences.

| Element | Meaning |
|---|---|
| the width of the violin | how many cores have a result around this value: wide where many cores are, thin where few are |
| the height of the violin | the range of the results, from the lowest core to the highest |
| the red line of the box | the median |
| the green dashed line of the box | the mean |
| the box, and the points outside | the quartiles, and the outliers |

A short, wide violin means homogeneous cores; a tall one, or one with several bulges, means cores behaving differently, like the busy and the idle cores of the `all_cores` view. With the NUMA views, there is one violin per NUMA domain, to compare the domains with each other.

## Per NUMA domain
![Core frequency per NUMA domain](img/hwgraph-env-freq-numa.png)

*`Freq/all_numa/Core frequency per NUMA domain.png`: one line per NUMA domain.*

![Core frequency per NUMA domain heatmap](img/hwgraph-env-freq-numa-heatmap.png)

*`Freq/all_numa/Core frequency per NUMA domain - heatmap.png`: the NUMA domains over the time, colored by frequency.*

## Benchmarks summary
`benchmarks_summary.txt` is the key to the benchmark names of the graphs. It starts with the
description of the host, and the NUMA domains with their cores when the trace has the topology,
then one row per benchmark, in the order they ran. From the [reference dataset](example/README.md):

```
Benchmarks summary - numa


System    : EXAMPLE0002 ProLiant DL385 Gen11
Bios      : v3.16
Kernel    : 6.18.52-611.el8.x86_64
Processor : 2x AMD EPYC 9124 16-Core Processor - 32 physical cores and 8 NUMA domains

NUMA nodes (8):
  NUMA 0 : [  0-  3], [ 32- 35]
  NUMA 1 : [  4-  7], [ 36- 39]
  …

Benchmark  Job  Engine / module  Variant  Workers  Pinned cores          NUMA nodes  Duration (s)
---------  ---  ---------------  -------  -------  --------------------  ----------  ------------
cpu_0      cpu  stressng / cpu   int128         2  [      0], [     32]        [ 0]           120
cpu_4      cpu  stressng / cpu   int128        10  [  0-  4], [ 32- 36]     [ 0- 1]           120
cpu_17     cpu  stressng / cpu   int128        36  [  0- 17], [ 32- 49]     [ 0- 4]           120
cpu_30     cpu  stressng / cpu   int128        62  [  0- 30], [ 32- 62]     [ 0- 7]           120
```

| Column | Content |
|---|---|
| `Benchmark` | the name of the benchmark, as in the output tree |
| `Job` | the job it was expanded from |
| `Engine / module`, `Variant` | the engine and the module, and the module parameter |
| `Workers` | the number of stressors |
| `Pinned cores` | the cores the benchmark was pinned to, or `no` |
| `NUMA nodes` | the NUMA domains of the pinned cores, `no` without pinning; `-` when the trace has no topology or no domain matches |
| `Duration (s)` | the `runtime` of the benchmark |

# Per chassis
Servers of a same chassis share their power supplies and their cooling: the chassis graphs
show the servers together, to see how each one weighs on the chassis.

They are enabled with `--same-chassis`, and automatically when there are several traces and
all of them report the same chassis serial number (`environment: All traces are from the same
chassis (<serial>), enabling --same-chassis feature`). The traces must be different servers,
each with a `BMC.Chassis` and a `BMC.Server` power metric, otherwise hwgraph explains why
they are not rendered, like `environment: server are not unique, disabling same-chassis print`.

For each benchmark, `environment/by_chassis/chassis/` contains:

| Graph | What it plots |
|---|---|
| `time_watt_<benchmark> <workers>x<engine>_<module>_<parameter>_chassis_by_Server` | the power of the chassis, of its power supplies, of the sum of the servers and of each server, from the `Server` metric |
| `time_watt_…_chassis_by_ServerInChassis` | the same, from the `ServerInChassis` metric; only when the BMC reports it |

# Per group
`--same-group` plots a group of servers, like the machines of a same rack, together. Every
trace must have the `BMC.Server` and the `CPU.package` power metrics, otherwise hwgraph stops with
`group: missing '<metric>' monitoric metric in <trace_filename>`.

The graphs add up the samples of the traces by their position: the first sample of every server with
the first sample of the others, and so on. The servers must therefore run the benchmark at the same
time, which is what [`sync_start`](configuration.md#sync_start)`=time` is made for, and with the same
number of samples: a server that misses one prints `Warning: <trace>/<benchmark>: Missing sample <n>,
considering 0 watts.`

For each benchmark, `by_group/` contains:

| Graph | What it plots |
|---|---|
| `time_watt_<benchmark> …_by_servers` | the power of each server, `BMC.Server` |
| `time_watt_<benchmark> …_by_group` | the sum of the servers: of `BMC.Server`, of `CPU.package`, and the difference between both, what the processors do not account for |
| `time_watt_percent_<benchmark> …_by_group` | the share of the CPU packages, and of the rest of the servers, in percent of the sum of `BMC.Server` |

The legend gives the `[min; mean; stddev; max]` of each curve. Beyond 36 servers, the most a legend
holds within the height of the graph, as for the other graphs, the legend of `…_by_servers` is
filled with the servers of the highest means, then a line `… <n> other servers between`, then the
servers of the lowest means, by decreasing mean; the servers between them are drawn without name.
The power of the sum has up to 15 ticks, at a round step: every 500 W for a rack of 8 servers,
every 5 kW for 128 servers.

For example, a group of four servers of the [reference dataset](example/README.md), which ran the
same benchmark at the same time while the cooling distribution unit was rebooted, with
the [event](hwgraph.md#events) `cdu_reboot:80:100`:

```bash
uv run hwgraph graph --same-group --no-env --no-scaling --no-versus --events cdu_reboot:80:100 \
    --traces documentation/example/traces/cdu_reboot.json:server-1:BMC.Server \
             documentation/example/traces/cdu_reboot_2.json:server-2:BMC.Server \
             documentation/example/traces/cdu_reboot_3.json:server-3:BMC.Server \
             documentation/example/traces/cdu_reboot_4.json:server-4:BMC.Server \
    --outdir graphs
```

![Power of each server](img/hwgraph-group-by-servers.png)

*`by_group/time_watt_… _by_servers.png`: the power of each of the four servers.*

![Sum of the servers](img/hwgraph-group-by-group.png)

*`by_group/time_watt_… _by_group.png`: the sum of the four servers. The processors slow down during the event, and the power of the group falls from about 4.6 kW to 3.1 kW, while the rest of the servers, the green line, increases during the event.*

![Share of the whole server](img/hwgraph-group-percent.png)

*`by_group/time_watt_percent_… _by_group.png`: what the CPU packages, and the rest of the servers, represent in percent of the power of the group: about 68% and 32% of the power, and about 35% and 65% during the event. The first sample is above 100%: at the beginning of the benchmark, the power reported by the BMC is lower than the one of the CPU packages.*

## Groups of the location
`--auto-group` finds the groups in the [location](hwgraph.md#location-of-the-servers) of the
servers, instead of taking all the traces as one group: it renders the graphs of a group for
each place shared by several traces, after the grouping by
[context](hwgraph.md#context-of-the-runs) of `--auto-traces`. It cannot be used with `--same-group`:
`argument --auto-group: not allowed with argument --same-group`.

hwgraph does not know what the places are, it only follows the paths of the locations: a place
holds the traces whose path starts the same way up to it. `by_group/` then holds the tree of
the places found, one subdirectory per place, from the widest, named after the place in ASCII,
after the name of its level when the location has levels, as the directory of a context. For example, two servers in the rack `A12` and two in the rack
`A13` of a same room:

```
by_group/Country_FR/Datacenter_PA99/Datahall_2/Room_1/            the four servers
by_group/Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12/   the two servers of the rack A12
by_group/Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A13/   the two servers of the rack A13
```

| Rule | Effect |
|---|---|
| a place | holds the traces whose path goes through it; the graphs give its location and its number of servers in their header, `Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 (4 servers)`, and its name in their file names, `time_watt_<benchmark> …_Room_1_by_group` |
| a place holding a single trace | not rendered: the group would be the server itself |
| a place holding the same traces as its single subplace | not rendered: its graphs would be the ones of the subplace; `Country_FR/`, `Datacenter_PA99/` and `Datahall_2/` above |
| servers at the same place, like the nodes of a chassis | a group of their whole location: `by_group/Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12/Position_23/` |
| a place not known, left empty | not a place, only a step to the next one: `FR / / A12`, without levels, is rendered in `by_group/FR/A12/` |
| a location of a single place, out of the hierarchy | the place of its servers: `by_group/Secret_Lab_1/` |
| locations of other hierarchies | compared by their paths alone: `PA3 / A12` and `FR / PA99 / A12` share no place; the names of the levels are shown only when all the servers of the place give the same |
| a trace without location | in no group |
| no place shared by several traces | nothing rendered: `auto-group: no place shared by several traces, nothing to group` |
| two places with the same directory name in ASCII | stops hwgraph: `auto-group: the places '<location>', '<location>' are all rendered in the directory <directory>` |

hwgraph prints the groups as a tree, each under the narrowest group holding it, with its number
of servers, the servers themselves being listed under it with `--verbose`. The graphs of a
group add up the same benchmarks of its servers, so every trace must have the benchmarks of
the first one of the group, with the same settings, and the `BMC.Server` and `CPU.package`
metrics. A group that does not is not rendered, the other groups are:

```
auto-group: 3 places shared by several traces, in by_group/:
  Country_FR/Datacenter_PA99/Datahall_2/Room_1     4 servers
    Rack_A12                                       2 servers, not rendered, server-2 does not have the benchmarks of server-1
    Rack_A13                                       2 servers
```

The other reasons are `<trace> has no '<metric>' metric in <benchmark>`, and the first line of
`Setting <benchmark>/<setting> does not match between <trace_filename> and <trace_filename>`.
As with `--same-group`, nothing tells whether the servers ran the benchmarks at the same time.
