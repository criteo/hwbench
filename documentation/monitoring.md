# Monitoring

hwbench is using a specific monitoring engine to collect data from several sources:
- [BMC](#bmc): thermal, fans and power of the server, through redfish
- [PDU](#pdu): the power of the outlets the server is connected to, through redfish
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

## Location
The `[Location]` section says where the target machine physically is: nothing in the machine
itself tells it. It is read whenever `-e` is given, even when the monitoring is disabled, and
is not a source: it has no `type`, nor credentials. A topology file given with `-t` replaces it,
locating every server of a fleet in a single file: see [topology.md](topology.md).

The keys go from the widest place to the narrowest one, each nested in the previous one: a
datacenter is in a country, a datahall in a datacenter, and so on down to the rack, where `U`
gives the height of the machine. The servers sharing a place, a datahall or a rack, share its
power and its cooling, which is what this order is made for. Every key is optional: only the
ones set are kept, so a location can start below the widest key, like a rack and a height.

| Key | Value | Effect |
|---|---|---|
| `Country` | text, like `FR` | the country of the datacenter |
| `Datacenter` | text, like `PA99` | the datacenter |
| `Datahall` | text, like `DH2` | the hall of the datacenter |
| `Room` | text, like `Room 1` or `Cage 1` | the room of the datahall, shown as is |
| `Rack` | text, like `A12` | the rack |
| `U` | text, like `23` | the height of the machine in the rack |
| `Extra` | free text, like `Secret Lab 1` | a place this hierarchy does not describe, set alone instead of the keys above |

The section name and the keys are not case sensitive. A key commented, absent or empty is not
set; without any key set, or without the section, the target machine has no location. Any other
key stops hwbench with `<environment_file>: unknown key '<key>' in the [Location] section,
expecting Country, Datacenter, Datahall, Room, Rack, U, Extra`, the key being given in lowercase.

For example:

```ini
[Location]
Country=FR
Datacenter=PA99
Datahall=DH2
Room=Cage 1
Rack=A12
U=23
```

hwbench prints the location at startup, from the widest key to the narrowest, `Rack` and `U`
before their value:

```
Startup: Location: FR / PA99 / DH2 / Cage 1 / Rack A12 / U23
```

and keeps the keys set as `location` in `results.json`, only when there is at least one, which
hwgraph shows under the serial of the server, see [hwgraph.md](hwgraph.md#location-of-the-servers),
and uses to group the servers by place with `--auto-group`:

```json
"location": {"Country": "FR", "Datacenter": "PA99", "Datahall": "DH2", "Room": "Cage 1", "Rack": "A12", "U": "23"}
```

With `Extra` alone, like `Extra=Secret Lab 1`, the location is `Secret Lab 1`.

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

