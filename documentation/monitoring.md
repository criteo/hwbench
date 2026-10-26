# Monitoring

hwbench is using a specific monitoring engine to collect data from several sources:
- [BMC](#bmc): thermal, fans and power of the server, through redfish
- [PDU](#pdu): the power of the outlets the server is connected to, through redfish
- [CDU](#cdu): cooling telemetry from configured cooling distribution units, using model-specific drivers
- [Turbostat](#turbostat): the power, frequency and IPC of the processor
- [all-smi](#all-smi): the inventory of the accelerators, and their power, frequency, utilization, memory and temperature

Depending on the source, power, frequency, thermal or cooling metrics are collected.

- [Concept](#concept)
- [Usage](#usage)
- [Configuration file](#configuration-file)
  - [BMC](#bmc)
    - [Generic driver](#generic-driver)
    - [Dell driver](#dell-driver)
    - [HPE driver](#hpe-driver)
    - [Metrics listed at startup](#metrics-listed-at-startup)
    - [Accelerators](#accelerators)
  - [PDU](#pdu)
    - [driver](#driver), [url](#url), [outlet](#outlet), [outletgroup](#outletgroup), [separator](#separator), [pdu_id](#pdu_id), [group](#group)
  - [CDU](#cdu)
    - [Configuration](#configuration), [Protocols](#protocols), [Supported models](#supported-models), [Collection and results](#collection-and-results)
  - [Location](#location)
- [Turbostat](#turbostat)
- [all-smi](#all-smi)
  - [Installing all-smi](#installing-all-smi)
  - [GPU locator](#gpu-locator)
  - [Accelerator metrics](#accelerator-metrics)

# Concept
During each benchmark, and if the monitoring is enabled, metrics are collected and aggregated over a period of time to get statistics. By default, they are collected every 2 seconds and aggregated every 10 seconds. These values are not configurable yet, which implies a `runtime` of at least 10 seconds for the monitoring to be usable: a shorter benchmark ends before the first aggregation, and gives no monitoring statistics at all.

> 💡 **Good practice**
>
> Prefer a `runtime` that is a multiple of 10 seconds. The metrics collected after the last
> aggregation are not part of any statistics: with `runtime=25`, the aggregations happen
> at 10 and 20 seconds, and the last 5 seconds of the benchmark are lost for the monitoring.

CDUs run in the same monitoring loop and use the same aggregation windows as the
host metrics. Each CDU is sampled on every host iteration. See [CDU](#cdu).

At the end of the benchmark the monitoring metrics are added in the result file. hwgraph will use them to plot how these components behave during the benchmark.

# Usage
To enable the monitoring feature, set the `monitor` directive in the configuration file to one of these values:

| Value | Effect |
|---|---|
| `all` | collect every metric the server exposes: power, thermal, fans, frequencies |
| `none` | no monitoring (default) |

`all` is the only way to enable the monitoring for now. In future releases, it will be possible to list the sources to be considered.

# Configuration file
When monitoring is enabled, the `-e <environment_file>` option must give the environment file, like `environment.cfg`, which describes the BMC and the PDUs of the target machine.
The former `-m`/`--monitoring-config` option stops hwbench with `-m is replaced by -e/--environment` (or `--monitoring-config is replaced by -e/--environment`).
This file is separated from the job file as it could be specific to each host.

Each source is defined like the following :

```
[section_name]
username=<username>
password=<password>
type=<type>
url=<url>
```

| Key | Value | Effect |
|---|---|---|
| `type` | `BMC`, `PDU`, `CDU` | the kind of source the section describes |
| `username`, `password` | text | the credentials of the source |
| `url` | the address of the source | how hwbench reaches it; optional for a BMC |

The keys specific to each kind of source are described below.

## BMC
When defining a BMC, the `type` must be set to `BMC`. The BMC type, and the driver used to
read it, are detected automatically, but the `section_name` selects the credentials used
for the server:

| Value | Effect |
|---|---|
| the vendor name: `DELL`, `HPE`, `AMD Corporation` or `GenericVendor` | the credentials of the servers of that vendor, selected first |
| `default` | the credentials of any server without a section for its vendor |

With any other name, the credentials are not read, and hwbench stops with
`Cannot find any valid BMC entry of the environment file`.

| Key | Value | Effect |
|---|---|---|
| `type` | `BMC` | mandatory |
| `username`, `password` | text | the credentials of the BMC |
| `url` | the address of the BMC | optional: detected at runtime via ipmitool, or ilorest on HPE systems |

A typical example looks like:

```
[HPE]
username=Administrator
password=YOURPASSWORD
type=BMC
```

A single BMC configuration is used per server.

A server without BMC, like a laptop, is detected as `GenericVendor`: without BMC section in
the environment file, hwbench does not look for its BMC.

> ℹ️ **Info**
>
> The `url` is read from the first section of type `BMC` of the file, whatever its name.
> With several BMC sections, the `url` can come from another section than the
> credentials: keep a single BMC section per file, or give the `url` in the first one.

The BMC code is using `redfish` endpoints to monitor the server. Vendor specific endpoints can be used in addition of the generic ones to get all meaningful metrics. This is automatic, the user has nothing to do: hwbench detects the vendor of the server and uses its endpoints when it has a dedicated driver for it, the generic ones otherwise.

At each start, hwbench **automatically detects** the resources the BMC exposes in the
thermal, fans and power categories. Nothing has to be listed in the configuration file:
whatever the BMC reports is monitored. How the resources are found depends on the driver
selected for the server, described below.

> ℹ️ **Info**
>
> The endpoints may vary with the vendor and the type of server: the paths, the number of
> chassis and the sensors each one exposes are defined by the BMC, not by hwbench.

To add the BMC of a server to the tests of the monitoring, [redfish-dump.md](redfish-dump.md)
records the urls hwbench reads from it, anonymized.

### Generic driver

Used on any server without a dedicated driver. It walks all the chassis listed by
`/redfish/v1/Chassis`, and follows the `Thermal` and `Power` links each one publishes, so
a BMC using other paths is followed as well. The temperatures are read from every
chassis; the fans, the power consumption and the power supplies only when a single
chassis exposes them, a BMC with several `Thermal` or `Power` resources giving none of
them.

| Category | Redfish endpoint | Field | Metrics |
|---|---|---|---|
| thermal | `/redfish/v1/Chassis/<chassis>/Thermal` | `Temperatures` | every temperature sensor with a reading, in Celsius |
| fans | `/redfish/v1/Chassis/<chassis>/Thermal` | `Fans` | every fan speed |
| power consumption | `/redfish/v1/Chassis/<chassis>/Power` | `PowerControl` | the power consumed by the server, in Watts |
| power supplies | `/redfish/v1/Chassis/<chassis>/Power` | `PowerSupplies` | the input power of every power supply, in Watts |

### Dell driver

Used on Dell servers, through their iDRAC. It reads the endpoints of the embedded system,
and completes the power consumption with the iDRAC attributes.

| Category | Redfish endpoint | Field | Metrics |
|---|---|---|---|
| thermal | `/redfish/v1/Chassis/System.Embedded.1/Thermal` | `Temperatures` | every temperature sensor with a reading, in Celsius |
| fans | `/redfish/v1/Chassis/System.Embedded.1/Thermal` | `Fans` | every fan speed |
| power consumption | `/redfish/v1/Chassis/System.Embedded.1/Power` | `PowerControl` | the power consumed by the server, in Watts |
| power consumption | `/redfish/v1/Chassis/System.Embedded.1/Power` | `PowerSupplies` | the chassis power: the sum of the power supplies, in Watts |
| power consumption | `/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/System.Embedded.1`, or `/redfish/v1/Managers/iDRAC.Embedded.1/Attributes` | `ServerPwr.1.SCViewSledPwr`, `SC-BMC.1.ChassisInfraPower` | on a multi-node chassis: the power of the server in its chassis, and of the chassis infrastructure, in Watts |
| power supplies | `/redfish/v1/Chassis/System.Embedded.1/Power` | `PowerSupplies` | the input power of every power supply, in Watts |

### HPE driver

Used on HPE servers, through their iLO. It reads the endpoints of the first chassis, the
power supplies from the HPE OEM fields, and the enclosure of a multi-node chassis.

| Category | Redfish endpoint | Field | Metrics |
|---|---|---|---|
| thermal | `/redfish/v1/Chassis/1/Thermal` | `Temperatures` | every temperature sensor with a reading, in Celsius, the index of their name dropped: `02-CPU 1 PkgTmp` becomes `CPU 1 PkgTmp` |
| fans | `/redfish/v1/Chassis/1/Thermal` | `Fans` | every fan speed |
| power consumption | `/redfish/v1/Chassis/1/Power/` | `PowerControl` | the power consumed by the server, in Watts; on an Apollo 2000 Gen10+, the power of the server in its chassis |
| power consumption | `/redfish/v1/Chassis/enclosurechassis/` | `Oem` → `Hpe` → `NodePowerWatts`, `ChassisPowerWatts` | on an Apollo 2000 Gen10+ multi-node chassis: the power of the server, and of the chassis, in Watts |
| power supplies | `/redfish/v1/Chassis/1/Power/` | `PowerSupplies` → `Oem` → `Hpe` → `AveragePowerOutputWatts` | the output power of every enabled power supply, named after its bay, in Watts |

### Metrics listed at startup

hwbench lists the metrics it found when the benchmarks start, one `Monitoring/BMC:` line
per category. On a Dell C6615:

```
Monitoring/BMC: Thermal metrics: 1xCPU, 1xIntake
Monitoring/BMC: Fans metrics: 10xFan
Monitoring/BMC: PowerConsumption metrics: 4xBMC
Monitoring/BMC: PowerSupplies metrics: 2xBMC
```

On x86_64, the `PowerConsumption` line also counts the CPU power measures of
[turbostat](#turbostat), like `65xCPU, 4xBMC` for a package and 64 cores. Here the BMC
exposes a CPU and an intake temperature sensor, 10 fans, 4 power consumption measures — the server from `PowerControl`, the chassis from the power
supplies, and the server in its chassis and the infrastructure from the iDRAC attributes
— and 2 power supplies.

Since the detection happens at each start, the monitoring follows the hardware actually
present: a replaced fan or an added power supply is picked up by the next run.

### Accelerators
If the BMC exposes accelerators, their metrics are collected too, using only the vendor neutral resources:
- the `Processors` of a `ComputerSystem` whose `ProcessorType` is `GPU`, through their `ProcessorMetrics` (temperature, consumed power, bandwidth and operating speed)
- when the BMC exposes none of those, the `Chassis` `Sensors` carrying a `GPU`, `Accelerator` or `GPUSubsystem` physical context. That walk reads every sensor of every chassis, so it is only done when the Processors did not already describe the accelerators.

Collections are read with the Redfish `$expand` query parameter when the service root advertises it, which returns a whole collection in a single request instead of one request per member. Support is optional and unevenly implemented, so the answer is checked rather than trusted: a service that does not advertise it, rejects the request, or accepts it and answers unexpanded falls back to reading the members one by one. A service that advertises it without honouring it is probed once, not on every monitoring iteration.

They are named `BMC_GPU_<redfish id>`, deliberately distinct from the `GPU_<n>` metrics all-smi reports: the Redfish ids of a BMC do not have to match the accelerator numbering. A BMC exposing none of those resources simply reports nothing.

> ℹ️ **Info**
>
> Hwbench monitoring code requires the BMC to be reachable from the host.

## PDU
When defining a PDU, the `section_name` is a user-defined value to represent this PDU.

| Key | Value | Effect |
|---|---|---|
| `type` | `PDU` | mandatory |
| `username`, `password` | text | the credentials of the PDU |
| [`driver`](#driver) | `generic` | mandatory: the code talking to the PDU |
| [`url`](#url) | the address of the PDU | mandatory |
| [`outlet`](#outlet) | outlet ids | the outlets the server is connected to; `outlet` or `outletgroup` is mandatory, not both |
| [`outletgroup`](#outletgroup) | outlet group ids | the outlet groups the server is connected to; `outlet` or `outletgroup` is mandatory, not both |
| [`separator`](#separator) | a character, default `,` | the separator of several outlets or outlet groups |
| [`pdu_id`](#pdu_id) | a member id, default `1` | the PDU behind a first one, when daisy-chained |
| [`group`](#group) | text, default empty | metadata for hwgraph |

A typical example looks like:

```
[myPDU]
username=admin
password=admin
type=PDU
driver=generic
url=https://mypdu/
outlet=21
```

> ℹ️ **Info**
>
> Several PDU configurations can be defined and used simultaneously.


### driver
There exist many PDU providers and the software quality may vary a lot and so the protocols. To ensure a good compatibility with them, drivers can be added to hwbench.

| Value | Effect |
|---|---|
| `generic` | the only driver for this release: it uses some redfish endpoints, so it might work on other products |
| `raritan` | a synonym for `generic`, kept for compatibility reasons |

The generic driver builds its redfish endpoints from the `pdu_id`, `outlet` and
`outletgroup` of the section:

| Category | Redfish endpoint | Field | Metrics |
|---|---|---|---|
| PDU identity | `/redfish/v1/PowerEquipment/RackPDUs/<pdu_id>/` | `Manufacturer`, `Model`, `FirmwareVersion`, `SerialNumber`, `UserLabel`, `Id` | the description of the PDU, stored in the results |
| power consumption | `/redfish/v1/PowerEquipment/RackPDUs/<pdu_id>/Outlets/<outlet>` | `PowerWatts` → `Reading` | the power of each listed outlet, summed, in Watts |
| power consumption | `/redfish/v1/PowerEquipment/RackPDUs/<pdu_id>/OutletGroups/<outletgroup>` | `PowerWatts` → `Reading` | the power of each listed outlet group, summed, in Watts |

If you have tested it on some other PDUs than raritan or enlogic or have created a custom driver, feel free to push a PR for review.

> ℹ️ **Info**
>
> The Generic driver only exports the power in Watts but can be expanded easily to get more metrics.


### url
The url cannot be automatically detected so it must be provided to hwbench.

| Value | Effect |
|---|---|
| `https://<pdu>/` | the address of the PDU; only `https` is accepted |

### outlet
This directive selects the physical outlet where the server is connected.

| Value | Effect |
|---|---|
| `<id>` | the outlet the server is connected to, like `21` |
| `<id>,<id>` | several outlets, all fetched for this PDU; the separator can be changed with [`separator`](#separator) |

### outletgroup
Some products support outlet groups where outlets from different PDUs are grouped in a single `outletgroup`.

If the PDU supports it, the `outletgroup` can be used to specify which one to use.

| Value | Effect |
|---|---|
| `<id>` | the outlet group the server is connected to, like `1` |
| `<id>,<id>` | several outlet groups, all fetched for this PDU |

A typical example looks like:

```
[PDU_with_grouped_outlets]
username=admin
password=admin
type=PDU
driver=raritan
url=https://mypdu/
outletgroup=1
```

> ℹ️ **Info**
>
> `outlet` and `outletgroup` are mutually exclusive.

### separator
By default, specifying multiple outlets or outletgroups for a given PDU is possible: using a comma as a separator, multiple outlets will be fetched for this PDU. This separator can be configured with the `separator`, when the outlet ids contain `,`.

| Value | Effect |
|---|---|
| `,` | the default separator |
| any other character | the separator of the `outlet` or `outletgroup` list, when the ids contain `,` |

### pdu_id
This property allows selecting the RackPDU member id. It is used to access daisy-chained PDUs that are accessible behind a first PDU. It is handled as a string.

| Value | Effect |
|---|---|
| `1` | the first PDU, the one reached by the url (default) |
| `<member id>` | a PDU daisy-chained behind the first one |

### group
This parameter is just metadata to be added in hwbench's output. The rendering software (hwgraph) can be used to group PDUs with the same group together. For example it can be used to annotate electrical feeds on which PDUs are attached to monitor for imbalance between them.

| Value | Effect |
|---|---|
| empty | no group (default) |
| `<name>` | the group of the PDU, like the electrical feed it is attached to |

For example, a server with 2 power supplies on each of two electrical feeds, `feed_A` and
`feed_B`, connected to outlets 21 and 22 of one PDU per feed:

```
[pdu_feed_A]
username=admin
password=admin
type=PDU
driver=generic
url=https://pdu-a/
outlet=21,22
group=feed_A

[pdu_feed_B]
username=admin
password=admin
type=PDU
driver=generic
url=https://pdu-b/
outlet=21,22
group=feed_B
```

> ℹ️ **Info**
>
> The group applies to a whole PDU section, and the outlets of a section are summed into a
> single power measure: outlets on different feeds need a section each, even when they
> are on the same PDU.

## CDU

hwbench supports cooling distribution units as monitoring sources alongside BMCs
and PDUs. Each configured CDU is identified by its vendor, model and protocol.
Its model driver defines the available readings and their units and conversions;
the shared collector and result format do not require a particular vendor,
number of sensors or set of metric names.

The initial model implementation is **HPE MCDU-4U-FR-2**, using **SNMP_V2C**.
Other models can be added to a vendor's registry, and other vendors have separate
model registries. A model using an existing protocol can reuse its transport
without changing the shared collector or graph renderer.

### Configuration

Each CDU gets its own section in the environment file. The section name identifies
it in the hardware inventory and results. The CDU vendor is independent of the
server vendor. Keep a BMC section and any PDU sections as usual.

| Key | Value | Effect |
|---|---|---|
| `type` | `CDU` | declares a cooling distribution unit |
| `vendor` | registered vendor name | selects the vendor's model registry |
| `model` | registered model name | selects the model driver and metric definitions |
| `protocol` | protocol supported by the selected model | selects the shared communication protocol and applicable credentials |
| `host` | hostname or IP address | the CDU's endpoint host |
| `timeout` | finite positive seconds | request timeout; defaults to `2` |
| `serial` | text | optional inventory metadata; no serial is inferred from the hostname |

Missing or unsupported vendor, model and protocol selections are rejected.
There is no fallback to another model's metric definitions or an implicit
protocol downgrade. Endpoint details and credentials belong to the protocol
driver, rather than the common CDU configuration.

Example for the currently supported HPE MCDU-4U-FR-2:

```ini
[CDU_cooling]
type=CDU
vendor=HPE
model=MCDU-4U-FR-2
protocol=SNMP_V2C
host=cdu.example.net
community=example-read-community
timeout=2
```

Replace `example-read-community` with the read community, then run
`uv run hwbench -j <job_file> -e <environment_file>`.

### Protocols

Protocol identifiers are shared across all CDU vendors and models:

| Identifier | Protocol |
|---|---|
| `SNMP_V2C` | SNMPv2c |
| `SNMP_V3` | Reserved identifier; no SNMPv3 driver is implemented |

Each model declares its supported subset of this catalogue. A globally known
identifier is accepted only when listed by the selected model, before credentials
are validated or any request is sent.

The shared SNMPv2c driver uses the Python `snmp` package (`python-snmp`),
installed automatically with hwbench. No `snmpget` executable or Net-SNMP
system package is required. It reads the OIDs supplied by the selected model
in one batched GET per poll.

Successful GET responses are cached for 1.5 seconds per driver instance, using
the same TTL as Redfish. Closely spaced calls reuse the response; at the normal
2-second host cadence, each iteration normally issues a new request. Exceptions
(including timeouts) are not cached. The cache is local to the hwbench process.
Each network request owns its SNMP engine; engines are never shared between threads.
The retransmission period is set beyond the response deadline, preventing retries.

| Key | Value | Effect |
|---|---|---|
| `port` | `161` by default | the SNMP UDP destination port |
| `community` | nonempty read community | required for SNMPv2c |

The read community must be nonempty. It is passed directly to the Python
library, never through a subprocess, temporary configuration file or log.
It is excluded from the hardware inventory and results, and from the copy of the environment
file in the output directory.

### Supported models

| Vendor | Model | Supported protocols | Readings |
|---|---|---|---|
| HPE | MCDU-4U-FR-2 | SNMP_V2C | 16 readings, described below |

These readings and conversions belong to the HPE MCDU-4U-FR-2 driver. Another
model supplies its own definitions and can expose different metrics or OIDs.

| Readings | Unit | Conversion from SNMP |
|---|---|---|
| Primary/secondary supply and return, ambient and PLC temperatures | Celsius | ×0.1 |
| Primary supply/return, secondary pump supply and secondary return pressures | raw | unchanged; engineering units remain unverified |
| Primary and secondary flows | L/min | ×0.1 |
| Valve position | Percent | unchanged |
| Relative humidity | Percent | ×0.1 |
| GRI pump 1 and pump 2 speeds | RPM | unchanged |

### Collection and results

Before the benchmarks, each CDU is read once, as the BMC and the PDUs, and hwbench
prints `Monitoring/CDU: <section>: <n>/<m> metrics read`. A CDU giving no reading,
unreachable or with a wrong community, stops hwbench with
`Monitoring/CDU: <section>: cannot read any metric: <errors>`. An SNMPv2c agent does not
answer a community it does not know, so a wrong community times out like an unreachable host:
the message then adds `no answer from <host> within <timeout>s, the community is probably wrong,
or the host unreachable`. hwbench stops with
`Monitoring/CDU: <section>: collection failed` when its driver fails, the error not being shown
as it may hold the credentials.

CDUs are polled synchronously on every iteration of the host monitoring loop,
starting on its first iteration. There is no separate CDU polling interval.
A slow request delays the loop, just like a BMC or
PDU request. `contexts.Monitor.CDU.Polling` records the total time spent in CDU
collection per host iteration. The SNMP response timeout is `timeout` seconds; address resolution
and processing also contribute to polling time.

The `hardware.cdu` inventory reports `type=CDU`, the configured `vendor`, `model`
and `protocol`. `monitoring.cdus.<section>` contains metric definitions (`name`,
`oid`, `unit`, `scale`), `timeout_s` and `readings`. Each reading has
`mean`, `min`, `max`, `stdev`, `samples` and `errors` arrays, with one entry per
host aggregation window. Errors are counted per reason within each window.
A window without valid readings has null statistics and zero samples. A real
numeric zero remains zero. Individual responses and timestamps are not stored.
As with host metrics, the unfinished final window is omitted.

hwgraph groups each CDU's readings by unit under
`environment/by_host/<trace>/<benchmark>/CDU/<index>-<section>/`. Metric names and
units come from the results. Graphs plot window means using the shared
`metadata.iteration_time`, leaving gaps for empty windows. The initial HPE model
produces five graphs: temperatures, raw readings, flows, percentage readings and
rotational speeds. Legend statistics describe the displayed window means, with
equal weight per valid window, rather than all raw readings. A separate `CDU and host temperatures_vs_PowerConsumption` graph
superposes circuit, CPU and GPU temperatures with CPU, selected trace and GPU power; see
[CDU and host comparison](hwgraph-environment.md#cdu-and-host-comparison).

## Location
The `[Location]` section says where the target machine physically is: nothing in the machine
itself tells it. It is read whenever `-e` is given, even when the monitoring is disabled, and
is not a source: it has no `type`, nor credentials. A topology file given with `-t` replaces it,
locating every server of a fleet in a single file: see [topology.md](topology.md).

The location is a path of places, from the widest to the narrowest, each nested in the
previous one, like a country, a datacenter, a room, a rack and a height in the rack. hwbench
does not impose these places: each infrastructure describes its own hierarchy, with as many
levels as it needs, and names them if it wants to. The servers sharing a place, a room or a
rack, share its power and its cooling, which is what this order is made for.

| Key | Value | Effect |
|---|---|---|
| `location` | the places, cut by the separator, like `FR / PA99 / 1 / A12 / 23` | where the machine is |
| `levels` | the names of the levels, cut by the separator, like `Country / DC / Room / Rack / Position` | optional: names the levels of the hierarchy, shown before their places |
| `separator` | text, `/` by default | what cuts the places of `location` and the names of `levels` |

The section name and the keys are not case sensitive, the spaces around each place and each
name are removed. A place is its value alone, its level telling what it is: `1` and `23`, not
`Room 1` and `U23`, the name of the level being shown before it, `Room 1` and `Position 23`.
Without `levels`, the places are shown alone, so they are better readable on their own. A place
left empty, like the room of `FR / PA99 / / A12`, is not known: it is not shown, but keeps its
level. Without `location`, or without any place known, the target
machine has no location.

A `location` of a single place, like `Secret Lab 1`, is out of the hierarchy: a place the
levels do not describe, like a lab. Any other `location` has one place for each level when
`levels` is given. hwbench stops otherwise, or for any other key, the key being given in
lowercase:

| Message | Cause |
|---|---|
| `<environment_file>: unknown key '<key>' in the [Location] section, expecting separator, levels, location` | a key the section does not know |
| `<environment_file>: the location '<location>' of the [Location] section has <n> places, expecting one for each of the <m> levels '<levels>', or a single one out of the hierarchy` | `location` and `levels` do not match |
| `<environment_file>: the levels '<levels>' of the [Location] section have an empty name` | a level without name |

For example:

```ini
[Location]
levels = Country / DC / DH / Room / Rack / Position
location = FR / PA3 / 12.34 / LH1234.12 / 12.23 / 3
```

hwbench prints the location at startup, each place after its level, joined by the separator:

```
Startup: Location: Country FR / DC PA3 / DH 12.34 / Room LH1234.12 / Rack 12.23 / Position 3
```

and keeps it as `location` in `results.json`, with its separator, and its levels when given,
which hwgraph shows under the serial of the server, see
[hwgraph.md](hwgraph.md#location-of-the-servers), and uses to group the servers by place with
`--auto-group`:

```json
"location": {"path": ["FR", "PA3", "12.34", "LH1234.12", "12.23", "3"], "separator": "/", "levels": ["Country", "DC", "DH", "Room", "Rack", "Position"]}
```

With `location = Secret Lab 1`, the location is `Secret Lab 1`, kept without levels.

# Turbostat
On x86_64 systems, turbostat is used automatically when the monitoring is enabled, and no configuration is required. It is mandatory there: hwbench stops with `Missing turbostat binary, please install it.` when it is not installed, or with `Monitoring/turbostat: minimal expected release is 2022.04.16` when it is older.

The following metrics are collected on the target machine:

| Metric | turbostat column | Granularity | Unit | In the results |
|---|---|---|---|---|
| CPU power consumption | `PkgWatt` | all the packages, summed | Watts | yes |
| core power consumption | `CorWatt` | per core | Watts | yes |
| memory power consumption | `RAMWatt` | all the packages, summed | Watts | yes |
| core frequency | `Bzy_MHz` | per core | MHz | yes |
| instructions per cycle | `IPC` | per core | IPC | yes |
| core busy time | `Busy%` | per core | % | not yet |
| time stamp counter frequency | `TSC_MHz` | per core | MHz | not yet |

The last two metrics are read from turbostat, but not stored in the results yet.

`RAMWatt` is optional: when turbostat prints nothing with it, hwbench warns with
`Monitoring/turbostat: no output with the optional columns RAMWatt, retrying without them`
and goes on without it. It is only requested when the kernel exposes the energy
counter of the memory: an `energy-ram` event in `/sys/bus/event_source/devices/power/events/`,
or a `dram` domain in `/sys/class/powercap/`. Some processors, like an Intel Core Ultra 7 165U,
show `RAMWatt` without metering their memory, and turbostat reports 0 Watts there.

> ℹ️ **Info**
>
> What is collected varies with the version of turbostat and the type of processor: a
> metric is only collected when turbostat reports its column on the target machine. Some
> processors do not report `CorWatt`, or not for all their cores, only the processors
> metering their memory report `RAMWatt`, and a virtual machine usually reports neither
> `Bzy_MHz` nor `PkgWatt`, which hwbench warns about at startup.

# all-smi
[all-smi](https://github.com/lablup/all-smi) is how hwbench finds the accelerators, not only how it monitors them. It covers NVIDIA, AMD, Intel and Apple GPUs as well as Gaudi, TPU, Tenstorrent, Rebellions and Furiosa NPUs, which is why hwbench goes through it rather than through a vendor tool. It gives:
- the accelerator inventory, recorded under `hardware.gpus` in the results: name, UUID, memory and the vendor properties, like the driver, VBIOS and ECC mode, completed with where each card sits (see [GPU locator](#gpu-locator));
- the indexes [`selected_gpus`](./configuration.md#selected_gpus) selects on;
- the per accelerator metrics below, sampled during the benchmarks.

Whether it is required depends on the job file:

| Job file | all-smi missing, older than 0.26.0 or reporting no accelerator |
|---|---|
| a job loads the GPUs, like a `pantheon` job | hwbench stops before running anything, with the other missing requirements |
| no job loads the GPUs | nothing is reported: the server is benchmarked without any GPU inventory nor GPU metrics |

When it is installed and reports accelerators, they are inventoried and monitored during every benchmark, whatever is loading them, and no configuration is required. The release is printed at startup, as for turbostat:

```
Monitoring/all-smi: Detected release 0.26.3
Monitoring/all-smi: initialize 8 GPUs
```

## Installing all-smi

Install it with `brew install all-smi`, from the Debian package, with `cargo install all-smi`, or from the `all-smi-linux-<arch>.tar.gz` archives of the [GitHub releases](https://github.com/lablup/all-smi/releases), which hold a single binary to put in the `PATH`. It is not published on PyPI. Note that `cargo install` does not ship the Linux AMD companion library, so use one of the packaged installs on an AMD host. The release must be 0.26.0 or newer, the first one with the `snapshot` and `api` subcommands hwbench is built on.

## GPU locator

A UUID does not say where a card is plugged, so each accelerator of the inventory also gets:

| Key | Value |
|---|---|
| `pci_address` | its PCI address, like `0000:1b:00.0`: read from `/proc/driver/nvidia/gpus/<address>/information` for an NVIDIA GPU, whose all-smi backend does not report it, and from the all-smi UUID for an Intel one; `null` otherwise |
| `slot` | the physical slot the kernel knows the card, or a PCIe switch above it, to be plugged in (`/sys/bus/pci/slots`, the `Physical Slot` of `lspci -v`); `null` when there is none |
| `locator` | `slot <slot>` when the slot is known, the PCI address otherwise: on a given chassis model, a PCI address is a fixed position too |

`hwgraph` lists the locator and the UUID of each GPU in `benchmarks_summary.txt`, so a GPU index of the results can be traced back to a card.

## Accelerator metrics

For each detected accelerator, sampled like every other source, hwbench collects:

| Metric | Context | Unit |
|---|---|---|
| Board power | `PowerConsumption.GPU` | Watts |
| Graphics frequency | `Freq.GPU` | Mhz |
| Utilization | `Utilization.GPU` | Percent |
| Used memory | `Memory.GPU` | MiB |
| Temperature | `Thermal.GPU` | Celsius |

Metrics are named `GPU_<n>`, the same way the CPU cores are named `Core_<n>`. The index is the order all-smi enumerated the accelerators in, and a card is tracked by its UUID so a reader returning them in another order cannot shift the metrics.

all-smi reports a quantity its backend cannot read as `0` rather than as a missing value. A powered board is never at 0 W, 0 Mhz or 0 degree, so those three are dropped instead of being recorded: they would otherwise poison the minimum and the mean of a card that simply exposes no such sensor. A utilization or a memory usage of zero, on the other hand, is a legitimate reading of an idle accelerator and is kept.

Rather than being forked once per iteration, which costs about 800ms of accelerator reader initialization and does not fit in a 2 seconds monitoring loop that also polls the BMC, all-smi is started once per benchmark as an exporter and polled over a unix socket, at 1.4ms per sample. Its TCP listener is disabled, so a benchmarked server gets no new open port.

