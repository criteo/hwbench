# redfish_dump: the BMC of a server as test fixtures

`tools/redfish_dump.py` records the Redfish urls hwbench reads from the BMC of the target
machine, with their answers, and writes them as the fixtures of the monitoring tests. The
values identifying the target machine, like its serial numbers or MAC addresses, are
replaced by placeholders, so the files can be committed.

The tool is multi-vendor by design: it detects the vendor like hwbench does, and records
the urls its BMC driver reads by running that driver. No url is listed per vendor in the
tool, and a read added to a driver is recorded as soon as it is added.

- [Usage](#usage)
- [Output](#output)
- [Anonymization](#anonymization)
- [Exploring other urls](#exploring-other-urls)
- [Implementation notes](#implementation-notes)

Related pages: [monitoring.md](monitoring.md) (the configuration file of the BMC, and the
metrics read from it).

# Usage

```bash
sudo uv run tools/redfish_dump.py -e environment.cfg -o hwbench/environment/tests/vendors/<vendor>/<model>
```

| Option | Value | Effect |
|---|---|---|
| `-e`, `--environment` | a file | mandatory: the [environment file](monitoring.md#configuration-file) of the target machine, the same file as `hwbench -e` |
| `-o`, `--output-directory` | a directory | mandatory: the directory to create, with its parents; an existing directory is never overwritten |
| `-u`, `--url` | an url | records this url too, see [Exploring other urls](#exploring-other-urls); can be repeated |

The tool connects to the BMC like hwbench does: the credentials, and the `url` of the BMC
if any, come from the [BMC section](monitoring.md#bmc) of the configuration file.

Like hwbench, it must run as root, otherwise it stops with `redfish_dump is not running as
effective uid 0: …`. The detection of the BMC needs it:

- on HPE servers, the driver logs in to the local iLO with `ilorest`, which needs root, at
  every run; without an `url` in the configuration file, `ilorest` also gives the address of
  the BMC;
- on the other servers, `ipmitool lan print` reads the address of the BMC through
  `/dev/ipmi0`, which only root can open; it runs at every detection, and its result is only
  used without an `url` in the configuration file.

The DMI information used to detect the vendor and the Redfish requests, sent over the
network, do not need root.

It runs, against the BMC, the detection of the BMC and one monitoring iteration, then
prints what it wrote. For example, on a HPE ProLiant DL365 Gen11:

```
HPE vendor with ILO driver @ https://<bmc> Model: 'iLO 6' FW: 'iLO 6 v1.77'
oem_chassis, power, thermal, redfish_tree written to /home/user/hwbench/hwbench/environment/tests/vendors/Hpe/DL365-Gen11
13 urls, 23 values anonymized
Check the files before committing them: an identifying value under an unknown key is not anonymized.
```

The first line, describing the BMC, holds its address: it is only shown, not written in
the files.

| Error | Cause |
|---|---|
| `ERROR:root:redfish_dump is not running as effective uid 0.` | the tool was not run as root |
| `ERROR:root:Directory <directory> already exists, please give a non-existent directory.` | `-o` names an existing directory |
| `ERROR:root:HPE vendor requires 'ilorest' tool, please install it.` | `ilorest` is missing on a HPE server |

> 💡 **Good practice**
>
> The files are written by root: give them back to your user, with `sudo chown -R`,
> before editing or committing them.

# Output

The directory has the layout of `hwbench/environment/tests/vendors/<vendor>/<model>/`,
each file being a python literal:

| File | Content |
|---|---|
| `redfish_tree` | each url read, with its answer: by the detection of the BMC, by one monitoring iteration (thermal, fans, power consumption, power supplies and [accelerators](monitoring.md#accelerators)), by the getters below, and the urls given with `-u` |
| `thermal`, `power` | the answer of the `get_thermal()` and `get_power()` methods of the BMC driver |
| `oem_*` | the answer of each `get_oem_*()` method of the BMC driver, like `oem_system` for the [Dell driver](monitoring.md#dell-driver) and `oem_chassis` for the [HPE driver](monitoring.md#hpe-driver) |

In `redfish_tree`, an url the BMC answered with an error is recorded as `{}`, and an url
it did not answer as `None`. An url read several times is recorded once, at its first
read: every file holds the same answer for the same url.

The files are the two kinds of fixtures of the tests:
- `hwbench/environment/test_dell.py` and `test_hpe.py` patch the getters of the driver
  with the `thermal`, `power` and `oem_*` files;
- `hwbench/environment/test_bmc_gpu.py` serves the whole `redfish_tree` to the BMC code,
  in place of the BMC.

# Anonymization

The secrets are redacted first: the value of a key ending with `password`, `salt`, `key`,
`passphrase`, `secret`, `community` or `token`, like the password hash and the IPMI and
SNMPv3 keys of a Dell iDRAC user, `Users.2.SHA256Password`, is replaced by `<redacted>`.
An empty secret is kept, to tell whether one is set, and so are the flags telling whether a
secret is used, like `Enabled` or `Disabled`.

The values identifying the target machine are replaced by placeholders. The same value
gets the same placeholder in every file, and in the urls: the links between the resources
are kept.

| Value | Placeholder |
|---|---|
| serial number, service tag and Dell express service code, processor PPIN, SNMP engine ID, common name of a certificate | `SERIAL<n>` |
| UUID | `00000000-0000-0000-0000-<n>` |
| hostname, and the host and the domain of a FQDN | `host<n>`, `domain<n>.example.com` |
| asset tag, user name | `ASSET<n>`, `user<n>` |
| MAC address, EUI-64 | `02` followed by `<n>`, with the length, the separators and the case of the original |
| IPv4, IPv6, email address | `192.0.2.<n>`, `2001:db8::<n>`, `user<n>@example.com` |

A value is found from the name of its key, like `SerialNumber`, `HostName`, `UUID` or
`MACAddress`, matched on its last dotted component for the Dell attributes, like
`ServerOS.1.HostName`. It is then replaced in every string it appears in, like a hostname
in the description of the operating system. A value of 6 characters or more is replaced
everywhere; a shorter one only when it is the whole value of an identifying key, as it
could be part of unrelated strings.

A value found under several keys, like a serial number used as hostname, gets the
placeholder of the first category of the table: `SERIAL<n>`.

A MAC address or an EUI-64 is found wherever it is written with separators, like
`6C:FE:54:94:37:50` or the identifier of a NVMe namespace in an UEFI device path, and
without separators in the `MAC()` node of an UEFI device path. The same address, written
with or without separators, gets the same number.

An IP address is also found in the urls, like the address of the BMC in the `URLString`
of the Dell iDRAC card. The host names of the urls are kept: they are public ones, like
`redfish.dmtf.org`.

An UUID is found wherever it is written, whatever its key, like the SMBIOS UUID of the
server a Dell repeats as `smbiosGUID`. The same UUID, written in upper or lower case, gets
the same number.

Neutral values are kept: under an identifying key, `Unknown`, `N/A`, `None`,
`Not Available`, `Not Specified`, the empty string, the flags `Enabled` and `Disabled`, as a
Dell attribute like `Autodiscovery.1.EnableIPChangeAnnounceFrommDNS` ends like a DNS server
key, and the default accounts `root`, `admin` and `Administrator`, whatever their case; and,
wherever they are found, the null addresses `0.0.0.0`, `::` and `00:00:00:00:00:00` (with or
without separators), the masks `255.*`, and the null UUID
`00000000-0000-0000-0000-000000000000`.

> 💡 **Good practice**
>
> Read the files before committing them: a value identifying the target machine under a
> key the anonymization does not know is kept as is.

# Exploring other urls

`-u` records an url hwbench does not read, to see what the BMC exposes before writing the
code that reads it. It is read with the same session, after the others, and anonymized
like them. For example, the 24 hours power history of an iLO:

```bash
sudo uv run tools/redfish_dump.py -e environment.cfg -o /tmp/dump -u /redfish/v1/Chassis/1/Power/PowerMeter/
```

Once hwbench reads an url, it is recorded without `-u`.

# Implementation notes

**Files.** The tool is `tools/redfish_dump.py`, a script out of the `hwbench` package
like `csv/convert.py`, tested by `tools/test_redfish_dump.py` and checked by `make check`.

**Detection.** `main()` detects the vendor with
`hwbench/environment/vendors/detect.py::first_matching_vendor()` in a temporary
directory, then connects with `BMC.connect_redfish()`.

**Recording.** `recording()` shadows `get_redfish_url()` on the BMC object with a
function recording each url and its answer, so every read of the driver is recorded,
whatever its vendor. `dump_fixtures()` runs, while recording, `BMC.detect()`,
`BMC.read_metrics()` (the reads of one monitoring iteration), each getter matching
`GETTERS`, then the urls of `-u`.

**Anonymization.** `anonymize()` first redacts the secrets with
`hwbench/environment/vendors/monitoring_device.py::redact_secrets()`. `Anonymizer` then
collects the identifying values of all the files, from `IDENTIFYING_KEYS`, `HEX_ID`,
`UEFI_MAC_ADDRESS`, `URL_IP_ADDRESS` and `UUID`, and replaces them: the placeholders are
numbered once for all the files.
