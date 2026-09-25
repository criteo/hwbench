# Monitoring

hwbench is using a specific monitoring engine to collect data from several sources:
- [BMC](#bmc): thermal, fans and power of the server, through redfish
- [PDU](#pdu): the power of the outlets the server is connected to, through redfish
- [Turbostat](#turbostat): the power, frequency and IPC of the processor

Depending on the source, power, frequency, thermal or cooling metrics are collected.

- [Concept](#concept)
- [Usage](#usage)
- [Configuration file](#configuration-file)
  - [BMC](#bmc)
    - [Generic driver](#generic-driver)
    - [Dell driver](#dell-driver)
    - [HPE driver](#hpe-driver)
    - [Metrics listed at startup](#metrics-listed-at-startup)
  - [PDU](#pdu)
    - [driver](#driver), [url](#url), [outlet](#outlet), [outletgroup](#outletgroup), [separator](#separator), [pdu_id](#pdu_id), [group](#group)
- [Turbostat](#turbostat)

# Concept
During each benchmark, and if the monitoring is enabled, metrics are collected and aggregated over a period of time to get statistics. By default, they are collected every 2 seconds and aggregated every 10 seconds. These values are not configurable yet, which implies a `runtime` of at least 10 seconds for the monitoring to be usable: a shorter benchmark ends before the first aggregation, and gives no monitoring statistics at all.

> 💡 **Good practice**
>
> Prefer a `runtime` that is a multiple of 10 seconds. The metrics collected after the last
> aggregation are not part of any statistics: with `runtime=25`, the aggregations happen
> at 10 and 20 seconds, and the last 5 seconds of the benchmark are lost for the monitoring.

At the end of the benchmark the monitoring metrics are added in the result file. hwgraph will use them to plot how these components behave during the benchmark.

# Usage
To enable the monitoring feature, set the `monitor` directive in the configuration file to one of these values:

| Value | Effect |
|---|---|
| `all` | collect every metric the server exposes: power, thermal, fans, frequencies |
| `none` | no monitoring (default) |

`all` is the only way to enable the monitoring for now. In future releases, it will be possible to list the sources to be considered.

# Configuration file
When monitoring is enabled, the `-m <config_file>` option must be used to describe the server's configuration.
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
| `type` | `BMC`, `PDU` | the kind of source the section describes |
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
`Cannot find any valid BMC entry of the monitoring configuration file`.

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

# Turbostat
On x86_64 systems, turbostat is used automatically when the monitoring is enabled, and no configuration is required. It is mandatory there: hwbench stops with `Missing turbostat binary, please install it.` when it is not installed, or with `Monitoring/turbostat: minimal expected release is 2022.04.16` when it is older.

The following metrics are collected on the target machine:

| Metric | turbostat column | Granularity | Unit | In the results |
|---|---|---|---|---|
| CPU power consumption | `PkgWatt` | all the packages, summed | Watts | yes |
| core power consumption | `CorWatt` | per core | Watts | yes |
| core frequency | `Bzy_MHz` | per core | MHz | yes |
| instructions per cycle | `IPC` | per core | IPC | yes |
| core busy time | `Busy%` | per core | % | not yet |
| time stamp counter frequency | `TSC_MHz` | per core | MHz | not yet |
| time in the C1 idle state | `C1%` | per core | % | not yet |
| time in the C2 idle state | `C2%` | per core | % | not yet |

The last four metrics are read from turbostat, but not stored in the results yet.

> ℹ️ **Info**
>
> What is collected varies with the version of turbostat and the type of processor: a
> metric is only collected when turbostat reports its column on the target machine. Some
> processors do not report `CorWatt`, or not for all their cores, and a virtual machine
> usually reports neither `Bzy_MHz` nor `PkgWatt`, which hwbench warns about at startup.
