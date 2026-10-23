# Topology: where the servers are

A topology file describes where the servers of an infrastructure are, in a JSON file following
the hierarchy of the [location](monitoring.md#location): country, datacenter, datahall, room,
rack and height in the rack. Given to hwbench with `-t`, it locates the target machine by its
serial, instead of the `[Location]` section of the environment file, so a single file, exported
from an inventory tool, locates every server of a fleet.

The format is versioned and described by a JSON schema, so that an exporter, written by hand or
generated, can produce it from any inventory tool: this page is its reference, written to be
enough to write one.

- [Format](#format)
- [Checking a topology](#checking-a-topology)
- [Using a topology with hwbench](#using-a-topology-with-hwbench)
- [Writing an exporter](#writing-an-exporter)
- [Versions of the format](#versions-of-the-format)
- [Implementation notes](#implementation-notes)

Related pages: [monitoring.md](monitoring.md#location) (the `[Location]` section the topology
replaces), [hwgraph.md](hwgraph.md#location-of-the-servers) (how the location is shown and used
to group the servers).

# Format
A topology is a JSON object with exactly three keys, all mandatory:

| Key | Value | Effect |
|---|---|---|
| `version` | `1` | the version of the format, see [Versions of the format](#versions-of-the-format) |
| `topology` | the hierarchy, from the countries | the servers of the datacenters |
| `extra` | an object, the place names to their serials | the servers out of the hierarchy |

## The hierarchy
`topology` nests 6 levels, always all of them, in this order. Each level is a JSON object
mapping the names of its places to the next level; the last one, `U`, maps each height to the
list of the serials of the servers at that height:

| Level | Name, like | Shown as | Holds |
|---|---|---|---|
| `Country` | `FR` | `FR` | the datacenters of the country |
| `Datacenter` | `PA99` | `PA99` | the datahalls of the datacenter |
| `Datahall` | `DH2` | `DH2` | the rooms of the datahall |
| `Room` | `Room 1`, `Cage 1` | `Cage 1` | the racks of the room |
| `Rack` | `A12` | `Rack A12` | the heights of the rack |
| `U` | `23` | `U23` | the list of the serials of the servers at this height |

hwbench adds `Rack ` and `U` to the names of these two levels when it shows them, so their names
do not hold them: `A12`, not `Rack A12`. The other names are shown as they are, so the name of a
room holds its kind, `Cage 1` rather than `1`. The country is its ISO 3166-1 alpha-2 code, like
`FR`; the schema does not check it.

The names are text, even the numbers, like `"23"`. A level that does not exist, or is not known,
keeps its place in the hierarchy with the name `""`: a datahall without rooms has a single room
`""`, a server whose height is not known is under the height `""`. The level is then not part of
the location of the server, like an empty key of the `[Location]` section.

The serials are a list, even for a single server: the nodes of a multi-node chassis share the
same height. A server spanning several heights is at the lowest one.

A serial is the one of the DMI of the server, `/sys/devices/virtual/dmi/id/product_serial`,
without the spaces at its ends: hwbench removes the ones some firmwares add before looking for
it. It is compared as is, upper and lower case being different.

## extra
`extra` holds the servers that the hierarchy does not describe, like the ones of a lab: it maps
a free text naming their place, like `Secret Lab 1`, to the list of their serials. Their
location is this text alone, `Extra` in the location keys. `extra` is mandatory, `{}` when it is
empty.

## Rules
| Rule | Checked by |
|---|---|
| the three keys `version`, `topology` and `extra`, and no other | the schema |
| exactly 6 levels in `topology`, ending with a list of serials | the schema |
| the names of the levels: text, `""` allowed, without spaces at their ends | the schema |
| the names of `extra` and the serials: text, not empty, without spaces at their ends | the schema |
| a list of serials: at least one, each once | the schema |
| a serial at a single place: once in the whole file, in `topology` or in `extra` | `tools/topology_check.py` |

## Example
The [`topology.json`](../topology.json) of the repository:

```json
{
  "version": 1,
  "topology": {
    "FR": {
      "PA99": {
        "DH2": {
          "Cage 1": {
            "A12": {
              "22": ["EXAMPLE0001"],
              "23": ["EXAMPLE0002"]
            },
            "A13": {
              "10": ["NODE0001", "NODE0002", "NODE0003", "NODE0004"]
            }
          }
        },
        "DH3": {
          "": {
            "B01": {
              "": ["EXAMPLE0003"]
            }
          }
        }
      }
    }
  },
  "extra": {
    "Secret Lab 1": ["LAB0001", "LAB0002"]
  }
}
```

It locates:

| Serial | Location |
|---|---|
| `EXAMPLE0002` | `FR / PA99 / DH2 / Cage 1 / Rack A12 / U23` |
| `NODE0001` to `NODE0004` | `FR / PA99 / DH2 / Cage 1 / Rack A13 / U10`: the 4 nodes of a chassis |
| `EXAMPLE0003` | `FR / PA99 / DH3 / Rack B01`: a datahall without rooms, a height not known |
| `LAB0001`, `LAB0002` | `Secret Lab 1` |

# Checking a topology
`tools/topology_check.py` checks a topology file before giving it to hwbench: the JSON schema of
its version, then what the schema cannot check, a serial at a single place. It does not need
root.

```bash
uv run tools/topology_check.py topology.json
```

| Option | Value | Effect |
|---|---|---|
| `topology` | a file | the topology file to check; mandatory, but with `--schema` |
| `-s`, `--serial` | a serial | also prints the location of this server |
| `--schema` | | prints the path of the JSON schema of the format, and exits |

A valid topology prints the number of its servers, and exits with 0:

```
$ uv run tools/topology_check.py topology.json --serial NODE0003
topology.json: valid topology, version 1: 7 servers in the topology, 2 in extra
NODE0003: FR / PA99 / DH2 / Cage 1 / Rack A13 / U10
```

An invalid one prints each problem, with where it is in the file as a JSON path, and exits
with 1:

```
topology.json: invalid topology:
  ["extra"]: a name cannot be empty
  ["topology"]["FR"]: ' PA1' has spaces at its ends
  ["topology"]["FR"]["PA99"]["DH2"]["Cage 1"]["A12"]["22"]: [] should be non-empty
  ["topology"]["FR"]["PA99"]["DH2"]["Cage 1"]["A13"]: ['NODE0001'] is not of type 'object'
  the document: Additional properties are not allowed ('owner' was unexpected)
```

A list of serials one level too high, like `['NODE0001']` above, is reported as not being an
object: a level is missing. The other problems are:

| Problem | Cause |
|---|---|
| `the document: '<key>' is a required property` | `version`, `topology` or `extra` is missing |
| `["version"]: unknown version <version>, expecting 1` | a version this hwbench does not know |
| `the serial '<serial>' is at several places: '<location>', '<location>'` | a serial found twice, in `topology` or in `extra` |
| `cannot read the topology: <error>` | the file cannot be read, or is not JSON |

With `--serial`, a serial that is in the file prints its location; one that is not prints
`<serial>: neither in the topology nor in extra`, and exits with 1.

# Using a topology with hwbench
`-t`, or `--topology`, gives the topology file to hwbench:

```bash
uv run hwbench -j configs/memory_load.conf -e environment.cfg -t topology.json
```

hwbench reads the serial of the target machine, `/sys/devices/virtual/dmi/id/product_serial`,
the `serial` of `hardware.dmi` in `results.json`, and takes its location in the topology. It
replaces the `[Location]` section of the environment file, which is then ignored: the location
is printed at startup, kept in `results.json` and shown by hwgraph as with the `[Location]`
section, see [monitoring.md](monitoring.md#location).

The topology must be valid, and must hold the target machine, otherwise hwbench stops before
running anything:

| Message | Cause |
|---|---|
| `<topology_file>: invalid topology, check it with tools/topology_check.py:` | followed by the problems listed by `tools/topology_check.py` |
| `<topology_file>: the serial '<serial>' of the target machine is neither in the topology nor in extra` | the target machine is not in the file |
| `Cannot find the serial of the target machine in /sys/devices/virtual/dmi/id/product_serial` | the serial cannot be read |

The topology file is copied as is in the output directory, as `topology.json`, so the
location of the run can be checked against the file it came from.

# Writing an exporter
An exporter reads an inventory tool, like a CMDB or a rack management tool, and writes a
topology file. Whatever its language, it:

1. maps each server of the inventory to the 6 levels, from the widest: the fields of the
   inventory rarely have the names of the levels, a "site" may be a datacenter, a "zone" a
   datahall, a "cage" or a "suite" a room. It writes the names as hwbench expects them, see
   [The hierarchy](#the-hierarchy): a cage `1` of the inventory is the room `Cage 1`, a rack
   `Rack A12` is the rack `A12`. An inventory without countries gives them from its sites, with
   a table of the exporter;
2. writes `""` for a level the inventory does not have, or does not know for a server, and
   never skips a level: the nesting is always 6 levels deep;
3. writes the names as text, even when the inventory stores numbers: the height `23` is `"23"`;
   and removes the spaces at their ends. A server spanning several heights is at the lowest;
4. writes the serial as the DMI of the server gives it, `product_serial`, with its case: the
   one of the chassis differs on some multi-node servers, and the one of a node is what hwbench
   looks for. An inventory with both writes the one of the node;
5. puts the servers at the same height in the same list, and each server at a single place;
6. puts the servers that are not in a datacenter, if any, in `extra`, under a free text naming
   their place. A server of a datacenter whose rack or height is not known stays in `topology`,
   with `""` for what is not known. The servers hwbench will never run on, like the ones in
   stock, at a reseller or decommissioned, may be left out: hwbench only looks for the target
   machine;
7. writes `"version": 1` and the three keys, `extra` being `{}` when empty, in UTF-8; the order
   of the keys does not matter;
8. checks its output with `tools/topology_check.py`, which prints every problem with its JSON
   path.

The schema, printed by `uv run tools/topology_check.py --schema`, is
[`hwbench/environment/topology-v1.schema.json`](../hwbench/environment/topology-v1.schema.json):
a JSON Schema, draft 2020-12, describing each level, usable to validate the output in the
language of the exporter.

# Versions of the format
`version` is the version of the format the file follows. hwbench and `tools/topology_check.py`
read the versions they know, each with its own schema, `topology-v<version>.schema.json`, and
refuse the others with `unknown version`. A change of the format, like a new level or a new key,
is a new version, with its own schema: the files of the previous versions stay valid.

| Version | Schema | Content |
|---|---|---|
| `1` | `topology-v1.schema.json` | the 6 levels from `Country` to `U`, the lists of serials, `extra` |

# Implementation notes
- `hwbench/environment/topology.py` reads the topology files: `read_topology()` reads a file and
  lists its problems with `topology_problems()`, which validates it with the schema of its
  version (`SCHEMAS`), then checks that each serial is at a single place. `servers()` walks a
  valid topology, giving each serial with its location, and `find_location()` finds the one of
  a serial.
- `LEVELS`, the levels of the hierarchy, are the keys of the location, `LOCATION_KEYS`, but
  `Extra`; a test checks that the schema chains the same levels.
- hwbench reads the serial of the target machine with `DmiSys.system_serial()`, finds its
  location with `topology_location()`, and copies the file with `save_topology()`.
- `tools/topology_check.py` is a script out of the package, like `tools/redfish_dump.py`.
