# Topology: where the servers are

A topology file describes where the servers of an infrastructure are, in a JSON file following
the hierarchy of its places, like the [location](monitoring.md#location) of the environment
file: a tree of places, from the widest to the narrowest, whose levels the infrastructure
chooses. Given to hwbench with `-t`, it locates the target machine by its serial, instead of the
`[Location]` section of the environment file, so a single file, exported from an inventory
tool, locates every server of a fleet.

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
A topology is a JSON object with these keys:

| Key | Value | Effect |
|---|---|---|
| `version` | `1`, mandatory | the version of the format, see [Versions of the format](#versions-of-the-format) |
| `topology` | the tree of the places, mandatory | where the servers are |
| `levels` | the names of the levels, from the widest, optional | like the `levels` of the `[Location]` section: names the levels, and fixes the depth of the tree |
| `separator` | text, `/` by default | what separates the places when the location of a server is shown |

## The tree of the places
`topology` is a tree with a single rule: it maps the names of places to what each place holds,
either the places it contains, a JSON object following the same rule, or the list of the
serials of the servers there. The path from the root to a list of serials is the location of
these servers, from the widest place to the narrowest, like `FR / PA99 / 2 / 1 / A12 / 23`.

A name is the value of the place alone, its level telling what it is: `1` and `23`, not
`Cage 1` and `U23`. hwbench and hwgraph show each place after the name of its level, like
`Room 1` and `Position 23`, when the topology gives its levels, and alone otherwise. They are
text, even the numbers, like `"23"`. A place that does
not exist, or is not known, keeps its level with the name `""`: a datahall without rooms has a
single room `""`, a server whose position is not known is under the position `""`. The place is
then not shown in the location, like an empty place of the `[Location]` section.

When `levels` is given, every list of serials is at its depth: with 6 levels, a server has 6
places. The only other depth allowed is 1: a list of serials right under the root is a place out
of the hierarchy, like the servers of a lab, `Secret Lab 1`, and these servers have a location
of a single place, without levels. Without `levels`, the lists of serials can be at any depth.

The serials are a list, even for a single server: the nodes of a multi-node chassis share the
same position. A server spanning several positions is at the lowest one: the bottom U of a 2U
server, the smallest number when the U are numbered from the bottom of the rack.

A serial is the one of the DMI of the server, `/sys/devices/virtual/dmi/id/product_serial`,
without the spaces at its ends: hwbench removes the ones some firmwares add before looking for
it. It is compared in uppercase, as an inventory may not keep the case the DMI gives:
`qtfcts0130298` in the topology locates the server whose DMI gives `QTFCTS0130298`.

## Rules
| Rule | Checked by |
|---|---|
| `version` and `topology`, optionally `levels` and `separator`, and no other key | the schema |
| a place holds either places or a list of serials | the schema |
| the names of the places: text, `""` allowed, without spaces at their ends | the schema |
| the names of the levels, the separator and the serials: text, not empty, without spaces at their ends | the schema |
| the levels: at least one, each once | the schema |
| a list of serials: at least one, each once | the schema |
| with `levels`, a list of serials at their depth, or right under the root | `tools/topology_check.py` |
| a list of serials with at least one known place | `tools/topology_check.py` |
| a serial at a single place: once in the whole file, compared in uppercase | `tools/topology_check.py` |
| a name of place without the separator, which would make the location ambiguous | a warning of `tools/topology_check.py` and hwbench |

## Example
The [`topology.json`](../topology.json) of the repository:

```json
{
  "version": 1,
  "levels": ["Country", "Datacenter", "Datahall", "Room", "Rack", "Position"],
  "topology": {
    "FR": {
      "PA99": {
        "2": {
          "1": {
            "A12": {
              "22": ["EXAMPLE0001"],
              "23": ["EXAMPLE0002"]
            },
            "A13": {
              "10": ["NODE0001", "NODE0002", "NODE0003", "NODE0004"]
            }
          }
        },
        "3": {
          "": {
            "B01": {
              "": ["EXAMPLE0003"]
            }
          }
        }
      }
    },
    "Secret Lab 1": ["LAB0001", "LAB0002"]
  }
}
```

It locates:

| Serial | Location |
|---|---|
| `EXAMPLE0002` | `Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23` |
| `NODE0001` to `NODE0004` | `Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10`: the 4 nodes of a chassis |
| `EXAMPLE0003` | `Country FR / Datacenter PA99 / Datahall 3 / Rack B01`: a datahall without rooms, a position not known |
| `LAB0001`, `LAB0002` | `Secret Lab 1`, out of the hierarchy |

# Checking a topology
`tools/topology_check.py` checks a topology file before giving it to hwbench: the JSON schema of
its version, then what the schema cannot check, the depth of the serials, a known place, and a
serial at a single place. It does not need root.

```bash
uv run tools/topology_check.py topology.json
```

| Option | Value | Effect |
|---|---|---|
| `topology` | a file | the topology file to check; mandatory, but with `--schema` |
| `-s`, `--serial` | a serial | also prints the location of this server |
| `--schema` | | prints the path of the JSON schema of the format, and exits |

A valid topology prints its levels and the number of its servers, and exits with 0:

```
$ uv run tools/topology_check.py topology.json --serial NODE0003
topology.json: valid topology, version 1, the levels Country / Datacenter / Datahall / Room / Rack / Position: 9 servers
NODE0003: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A13 / Position 10
```

An invalid one prints each problem, with where it is in the file as a JSON path, and exits
with 1:

```
topology.json: invalid topology:
  ["levels"][6]: a name cannot be empty
  ["topology"]["FR"]: ' PA1' has spaces at its ends
  ["topology"]["FR"]["PA99"]["2"]["1"]["A12"]["22"]: [] should be non-empty
  ["topology"]["FR"]["PA99"]["2"]["1"]["A13"]["10"]: 'NODE0001' is not of type 'object'
  the document: Additional properties are not allowed ('owner' was unexpected)
```

A serial given as a text instead of a list, like `'NODE0001'` above, is reported as not being
an object: a place holds either places or a list. The problems found once the schema is
followed are:

| Problem | Cause |
|---|---|
| `<path>: serials at the level <depth>, expecting the <n> levels <levels>, or a single place out of the hierarchy` | with `levels`, a list of serials at another depth |
| `<path>: serials without any known place` | a list of serials whose places are all `""` |
| `the serial '<serial>' is at several places: '<location>', '<location>'` | a serial found twice |

The other problems are `the document: '<key>' is a required property`, when `version` or
`topology` is missing, `["version"]: unknown version <version>, expecting 1`, for a version this
hwbench does not know, and `cannot read the topology: <error>`, when the file cannot be read,
or is not JSON.

A place whose name holds the separator, like the rack `A12/B` with the separator `/`, makes the
locations through it ambiguous: the topology stays valid, but `tools/topology_check.py` prints a
warning on stderr, proposing a separator none of the names holds, to give with `separator`:

```
topology.json: warning: ["topology"]["FR"]["PA99"]["2"]["1"]: the place 'A12/B' holds the separator '/', its locations are ambiguous: give another one with "separator", like '|'
```

hwbench logs the same warning when it reads the topology, and runs.

With `--serial`, a serial that is in the file prints its location; one that is not prints
`<serial>: not in the topology`, and exits with 1.

# Using a topology with hwbench
`-t`, or `--topology`, gives the topology file to hwbench:

```bash
uv run hwbench -j configs/memory_load.conf -e environment.cfg -t topology.json
```

hwbench checks the topology before tuning the host. Once it has dumped the hardware environment,
it reads the serial of the target machine in its DMI, `product_serial`, the `serial` of
`hardware.dmi` in `results.json`, and takes its location in the topology. It
replaces the `[Location]` section of the environment file, which is then ignored: the location
is printed at startup, kept in `results.json`, with the separator and the levels of the
topology, and shown by hwgraph as with the `[Location]` section, see
[monitoring.md](monitoring.md#location).

The topology must be valid, and must hold the target machine, otherwise hwbench stops before
running any benchmark:

| Message | Cause |
|---|---|
| `<topology_file>: invalid topology, check it with tools/topology_check.py:` | followed by the problems listed by `tools/topology_check.py` |
| `<topology_file>: the serial '<serial>' of the target machine is not in the topology` | the target machine is not in the file |
| `<topology_file>: the target machine has no serial in its DMI to find it in the topology` | the serial cannot be read, or is empty |

The topology file is copied as is in the output directory, as `topology.json`, so the
location of the run can be checked against the file it came from.

# Writing an exporter
An exporter reads an inventory tool, like a CMDB or a rack management tool, and writes a
topology file. Whatever its language, it:

1. chooses the levels of the hierarchy from the fields of the inventory, from the widest, like
   a site, a cage, a rack and a slot, and writes them in `levels`. An inventory without a level
   the infrastructure needs, like the country, gives it from a table of the exporter;
2. writes the value of each place alone, its level telling what it is: a cage `1` of the
   inventory is the place `1` of the level `Cage`, not `Cage 1`, a slot `23` is `23`;
3. writes `""` for a place the inventory does not have, or does not know for a server, and never
   skips a level: with `levels`, every list of serials is at their depth;
4. writes the names as text, even when the inventory stores numbers, and removes the spaces at
   their ends. A server spanning several positions is at the lowest, its bottom U: an inventory
   giving another one, like its top U, is converted;
5. writes the serial of the server, the one its DMI gives as `product_serial`, whatever its
   case, compared in uppercase: the one of the chassis differs on some multi-node servers, and
   the one of a node is what hwbench looks for. An inventory with both writes the one of the
   node;
6. puts the servers at the same position in the same list, and each server at a single place;
7. leaves out the servers without rack, and the ones out of production, like the ones in
   stock, at a reseller or decommissioned: they are not in the hierarchy, and hwbench does not
   run on them. A server in a rack keeps `""` for a place the inventory does not know, like its
   position. A list right under the root is only for servers at a place the hierarchy does not
   describe, like a lab, when the inventory knows them;
8. leaves out a server without any known place, whose places would all be `""`, and a serial
   the inventory gives twice, writing it once;
9. checks that no name of place holds the separator, or chooses another one, given with
   `separator`;
10. writes `"version": 1`, in UTF-8; the order of the keys does not matter;
11. checks its output with `tools/topology_check.py`, which prints every problem with its JSON
    path.

The schema, printed by `uv run tools/topology_check.py --schema`, is
[`hwbench/environment/topology-v1.schema.json`](../hwbench/environment/topology-v1.schema.json):
a JSON Schema, draft 2020-12, describing the tree with a single recursive definition, usable to
validate the output in the language of the exporter.

# Versions of the format
`version` is the version of the format the file follows. hwbench and `tools/topology_check.py`
read the versions they know, each with its own schema, `topology-v<version>.schema.json`, and
refuse the others with `unknown version`. A change of the format, like a new key, is a new
version, with its own schema: the files of the previous versions stay valid.

| Version | Schema | Content |
|---|---|---|
| `1` | `topology-v1.schema.json` | the tree of the places, its optional levels and separator |

# Implementation notes
- `hwbench/environment/topology.py` reads the topology files: `read_topology()` reads a file and
  lists its problems with `topology_problems()`, which validates it with the schema of its
  version (`SCHEMAS`), then checks the depth of the serials, their known place, and that each
  serial is at a single place, in uppercase. `separator_warnings()` lists the places whose name
  holds the separator, with a separator to propose from `OTHER_SEPARATORS`. `leaves()` walks the tree, giving each list of serials with the
  path of its places, `servers()` gives each serial with its `Location`, the class of
  `hwbench/environment/environment_file.py` the `[Location]` section gives too, and
  `find_location()` finds the one of a serial.
- hwbench checks the file with `load_topology()` and copies it with `save_topology()` before
  tuning the host, then finds the location of the serial of the DMI dumped by `Hardware`,
  `hw.dmi.info("product_serial")`, with `topology_location()`.
- `tools/topology_check.py` is a script out of the package, like `tools/redfish_dump.py`.
