# Monitoring

hwbench is using a specific monitoring engine to collect data from several sources :
- BMC
- PDU
- Turbostat

Regarding the source, power, frequencies, thermal or cooling metrics are collected.

# Concept
During each benchmark, and if the monitoring is enabled, metrics are collected every 2 seconds and aggregated every 10 seconds to get statistics over this period of time.

At the end of the benchmark the monitoring metrics are added in the a result file. hwgraph will use them to plot how these components behave during the benchmark.

# Usage
To enable the monitoring feature, just set the `monitor` directive in the configuration file.

As per this release, only `monitor=all` is supported. In future releases, it will be possible to list the source to be considered.

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

 ## BMC
 When defining a BMC, the `type` must be set to `BMC`. The `section_name` could the hardware vendor name like `DELL`, `HPE`, or `default`.

 A typical example looks like :
 
```
[HPE]
username=Administrator
password=YOURPASSWORD
type=BMC
```

**Note**: if no ``url`` parameter is provided, it will be automatically detected at runtime via ipmitool tool (or ilorest on HPE systems).

A single BMC configuration will be used per server and vendor specific will be selected first if matching the running hardware.

The BMC code is using `redfish` endpoints to monitor the server. Vendor specific endpoints can be used in addition of the generic ones to get all meaningful metrics.

Hwbench monitoring code requires the BMC to be reachable from the host.

## PDU
When defining a PDU,
- a `section_name`, a user-defined value to represent this PDU
- the ``type`` must be set to `PDU`.
- a ``driver`` must be chosen
- an ``URL`` is required
- the ``outlet`` port must be selected

 A typical example looks like :

```
[myPDU]
username=admin
password=admin
type=PDU
driver=raritan
url=http://mypdu/
outlet=21
```

**Note**: Several PDU configurations can be defined and used simultaneously.


### Driver
There exist many PDU providers and the software quality may vary a lot and so the protocols. To ensure a good compatibility with them, drivers can be added to hwbench.

For this release, only **raritan** driver exists but as it uses some redfish endpoints, it might work on other products.

If you have tested it on some other PDUs or have created a custom driver, feel free to push a PR for review.

**Note**: The Raritan driver only exports the power in Watts but can be expanded easily to get more metrics.



## URL
The url cannot be automatically detected so it must be provided to hwbench.

## Outlet
This directive selects the physical outlet where the server is connected.

## Outletgroup
Some products support outlet groups where outlets from different PDUs are grouped in a single `outletgroup`.

If the PDU supports it, the `outletgroup` can be used to specify which one to use.
A typical example looks like :

```
[PDU_with_grouped_outlets]
username=admin
password=admin
type=PDU
driver=raritan
url=https://mypdu/
outletgroup=1
```

**Note**: ``outlet`` and ``outletgroup` are mutually exclusive.

# Turbostat
Turbostat will be automatically used on x86_64 systems if already installed on the server with release >= 2022.04.16. No configuration is required.