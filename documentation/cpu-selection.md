# Selecting CPUs

`selected_cpus` and `selected_cpus_scaling` decide *where* a benchmark runs. They are the
two hardest keywords of hwbench, because together they turn one line of configuration
into a whole series of benchmarks.

- [The mental model](#the-mental-model)
  - [A simple example](#a-simple-example)
  - [The same domains, a different load](#the-same-domains-a-different-load)
  - [In words](#in-words)
- [Reading the maps](#reading-the-maps)
- [selected_cpus: which CPUs this job will use](#selected_cpus-which-cpus-this-job-will-use)
- [Groups: the rule that changes everything](#groups-the-rule-that-changes-everything)
- [selected_cpus_scaling: turning those CPUs into benchmarks](#selected_cpus_scaling-turning-those-cpus-into-benchmarks)
- [Helpers](#helpers)
- [What it costs in time](#what-it-costs-in-time)
- [Previewing a job file: --dry-run](#previewing-a-job-file---dry-run)
- [Implementation notes](#implementation-notes)

How many stressors run on those CPUs is the other dimension, described in
[`stressor_range`](configuration.md#stressor_range).

# The mental model

In one sentence: **`selected_cpus_*` is how you slice the processor,
`stressor_*` is how you test each slice.**

| Keyword | What it defines | What it produces |
|---|---|---|
| `selected_cpus` | which CPUs of the target machine will be used for this job | a list of CPUs to test |
| `selected_cpus_scaling` | the iteration method over the CPUs listed by `selected_cpus` | the list of CPUs to test at each iteration |
| `stressor_range` | how the number of stressor instances evolves in the CPU group of each iteration | a list of stressor counts |
| `stressor_range_scaling` | the iteration method over the counts listed by `stressor_range` | one benchmark per iteration |

The benchmark is what finally runs, pinned on the CPUs it was given. Note that
`stressor_range` sets the *number* of instances, not which CPU each one lands on: the
benchmark is pinned on the whole list and the kernel places the instances inside it.

## A simple example

Let's take an example where the user wants to test the first two NUMA domains, each
domain on its own, with as much load as the domain has cores. That intention becomes:

```ini
selected_cpus=numa0 numa1
selected_cpus_scaling=iterate
stressor_range=auto
stressor_range_scaling=plus_1
```

On a CPU with 8 NUMA domains of 16 logical CPUs each, the chain runs like this:

```
keyword                 what it does                            hwbench's view
----------------------  --------------------------------------  -----------------------------
selected_cpus           keeps the cpus of the two domains       [[0-7,64-71], [8-15,72-79]]
selected_cpus_scaling   walks the groups one by one             [0-7,64-71] then [8-15,72-79]
stressor_range          as many stressors as cpus in the group  [16]
stressor_range_scaling  one benchmark per count                 [bench 0, bench 1]
```

**2 benchmarks**, each pinned on the CPUs it was given.

```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         ########........................................................  16
bench 1         ........########................................................  16
```

One column is one physical core, `#` means it is pinned; the full legend is in
[Reading the maps](#reading-the-maps).

> ℹ️ **Info**
>
> The two views do not count the same thing: `hwbench's view` lists **logical** CPUs, as
> the kernel numbers them, while the map has one column per **physical** core. The group
> `[0-7,64-71]` is 16 logical CPUs, that is physical cores 0 to 7 with both their SMT
> threads, hence 8 `#` on the map.

`stressor_range_scaling=plus_1` is the default and walks every count; the first examples
spell it out so no step of the chain stays invisible.

Change one keyword and the shape changes: `selected_cpus=numa0,1` would put both domains
in a single group, hence a single benchmark of 32 stressors, and `stressor_range=1,2,4`
would give three benchmarks per domain instead of one.

## The same domains, a different load

Now the user wants to know how each of those two domains behaves as the load grows: 1
stressor, then 2, 4, 8, and finally all 16 cores. **Only the stressor keywords change**,
the CPU selection is untouched:

```ini
selected_cpus=numa0 numa1
selected_cpus_scaling=iterate
stressor_range=1,2,4,8,16
stressor_range_scaling=plus_1
```

```
keyword                 what it does                        hwbench's view
----------------------  ----------------------------------  -----------------------------
selected_cpus           keeps the cpus of the two domains   [[0-7,64-71], [8-15,72-79]]
selected_cpus_scaling   walks the groups one by one         [0-7,64-71] then [8-15,72-79]
stressor_range          five stressor counts to walk        [1, 2, 4, 8, 16]
stressor_range_scaling  one benchmark per count, per group  [bench 0 ... bench 9]
```

**10 benchmarks**: five stressor counts on each of the two domains.

```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         ########........................................................   1
bench 1         ########........................................................   2
bench 2         ########........................................................   4
bench 3         ########........................................................   8
bench 4         ########........................................................  16
bench 5         ........########................................................   1
bench 6         ........########................................................   2
bench 7         ........########................................................   4
bench 8         ........########................................................   8
bench 9         ........########................................................  16
```

The group of CPUs does not move for five benchmarks in a row: only the stressor count
in the right margin changes, then the next domain is taken.

Same slices, five times more benchmarks, and a different question answered:

| Intention | `stressor_range` | Benchmarks | Duration at `runtime=120` |
|---|---|---|---|
| how fast is each domain, fully loaded | `auto` | 2 | 4 min |
| how does each domain scale with the load | `1,2,4,8,16` | 10 | 20 min |

This is what the `stressor_*` keywords are for: the CPU keywords decide *what is being
tested*, the stressor keywords decide *how it is being loaded*. A slice loaded to its
last core gives the aggregated performance of that slice; the same slice walked from 1
stressor upwards shows where it stops scaling.

Studying **each core** of those domains is a different question again, and this time the
CPU selection is what has to change — see
[Groups](#groups-the-rule-that-changes-everything).

## In words

`selected_cpus` never creates a benchmark by itself: it declares which CPUs will be
used for the benchmarks of this job, as **groups** of logical CPUs. `selected_cpus_scaling`
defines the iteration method over that list, and what it produces at each step is **the
list of CPUs to test**: one group at a time, all of them merged into one, or accumulated
step by step.

Only then, **for each list of CPUs to test**, [`stressor_range`](configuration.md#stressor_range) gives the
stressor counts to walk and `stressor_range_scaling` turns each count into a benchmark — and
`engine_module_parameter` multiplies them once more, each parameter giving its own benchmarks.
The benchmark created at the end of that chain is the one carrying the pinning.

Almost every surprise with these keywords comes from the number of groups being
different from what was intended.

# Reading the maps

Most of this page is illustrated with the same kind of ASCII map. The point is to show
what a job *produces*, not what it says: one benchmark per line, the whole CPU on every
line, so a series of benchmarks can be compared by reading down the block — whether the
pinning moves, grows, or stays put while only the load changes.

The examples all use the same CPU: an **AMD EPYC 8534P**, 64 physical cores, 128 logical
CPUs, 8 NUMA domains, 4 quadrants, one socket. Unless written otherwise, they also use
`stressor_range=auto` and `runtime=120`: the ini snippets only show the keywords that
change from one example to the next.

```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         ########........................................................   16
bench 1         ........########................................................   16
```

| Part of the map | Meaning |
|---|---|
| a column | one **physical core**, from 0 to 63 |
| a line | one **benchmark**, in the order hwbench runs them |
| the `physical core` ruler | the core number every 8 cores, and always the last core, so the end of the CPU is visible |
| the `numa domain` ruler | the NUMA domain each core belongs to; with more than 10 domains, the number is written vertically, tens above units, so domain 13 is a `1` above a `3` |
| the `quadrant` ruler | the quadrant each core belongs to, shown when the CPU has more than one |
| the `socket` ruler | the socket each core belongs to, shown on a multi-socket machine |
| the right column | the number of stressor instances of that benchmark |

This CPU has SMT, so each physical core carries two logical CPUs — on the 8534P core
*n* owns cpu *n* and cpu *n+64*, but the numbering is machine specific. The CPU lists
printed by hwbench, in its output and in the `hwbench's view` column of the examples, are
always **logical** CPUs; only the maps count physical cores. Rather than drawing two lines
per benchmark, the glyph says which thread of the core is pinned:

| Glyph | Meaning |
|---|---|
| `#` | both logical CPUs of the core are pinned |
| `1` | only the first thread of the core is pinned |
| `2` | only the second thread of the core is pinned |
| `+` | some of the threads of the core are pinned, on a CPU with more than 2 threads per core |
| `.` | the core is not part of the pinning |
| `-` | on the whole line: the benchmark is not pinned at all |

> ℹ️ **Info**
>
> Two limits worth knowing. The map shows the **pinning**, that is the CPUs the benchmark
> is allowed to use; hwbench decides how many stressor instances run there, but the kernel
> decides which of those CPUs actually get busy. And the maps are generated from a real
> expansion on that mocked topology, so the counts are exact, but another CPU will give
> different numbers.

# selected_cpus: which CPUs this job will use

The accepted values — CPU numbers, `core<x>`, `numa<x>`, `quadrant<x>`, the `each-*`
helpers, `all` and `none` — the group syntax and the errors are listed in
[configuration.md](configuration.md#selected_cpus), the reference of every keyword. This
section shows what they select on a real CPU, the AMD EPYC 8534P of this page, whose 8
NUMA domains hold 8 cores each. The same value gives different CPUs on another processor.

| Value | Effect |
|---|---|
| `12`, `0-7`, `0,2,4` | those logical cpus — meaningful only for a given numbering of the logical CPUs |
| `core0` | cpu 0 and 64, the two threads of the first physical core |
| `numa0` | 16 logical cpus: cores 0 to 7 with their second threads |
| `quadrant0` | 32 logical cpus: the two first NUMA domains |
| [`each-core`](#each-core-each-numa-each-quadrant) | 64 groups of 2 logical cpus |
| [`each-numa`](#each-core-each-numa-each-quadrant) | 8 groups of 16 logical cpus |
| [`each-quadrant`](#each-core-each-numa-each-quadrant) | 4 groups of 32 logical cpus |
| `all` | cpu 0-127, as a single group |
| `none` | no pinning at all |

## NUMA domains and quadrants

`numa<x>` and `quadrant<x>` are the two keywords that express locality, and on AMD they
follow two distinct BIOS settings:

| Key | Value | Effect |
|---|---|---|
| NPS (NUMA nodes Per Socket) | `NPS1`, `NPS2`, `NPS4` | how the memory controllers (DDR) are associated to the cores: 1, 2 or 4 groups per socket, the **quadrants** |
| L3 cache as NUMA domain (LLC as NUMA) | enabled | each L3 cache, with the cores sharing it, is exposed as a **NUMA domain** |

Without LLC as NUMA, a NUMA domain is a quadrant. With it, a quadrant holds several NUMA
domains, the ones sharing its memory controllers; hwbench finds them in the NUMA
distances, as the domains closer than 12 to each other. The 8534P used here runs in NPS4
with LLC as NUMA: 4 quadrants, of two NUMA domains, two L3 caches, each. That is exactly
the kind of difference you want to see in a graph rather than compute by hand.

> ℹ️ **Info**
>
> What `numa<x>` measures depends on the BIOS settings of the target machine: an L3 cache
> with LLC as NUMA, a quadrant without it. The job file cannot know it in advance: the
> NUMA domains and the quadrants hwbench detects are shown by
> [`--dry-run`](#previewing-a-job-file---dry-run), and the NUMA domains with their
> distances are kept in the hardware section of `results.json`.

The two maps below show the same kind of job, with only `selected_cpus` changing.

**`numa<x>`: one benchmark per NUMA domain**

```ini
selected_cpus=numa0 numa1
selected_cpus_scaling=iterate
stressor_range=auto
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         ########........................................................  16
bench 1         ........########................................................  16
```

`numa0` then `numa1`: 8 physical cores each, that is 16 logical CPUs and 16 stressors.

**`quadrant<x>`: one benchmark per quadrant**

```ini
selected_cpus=quadrant0 quadrant1 quadrant2 quadrant3
selected_cpus_scaling=iterate
stressor_range=auto
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
quadrant        0000000000000000111111111111111122222222222222223333333333333333
bench 0         ################................................................  32
bench 1         ................################................................  32
bench 2         ................................################................  32
bench 3         ................................................################  32
```

`quadrant0` to `quadrant3`: each quadrant covers two NUMA domains, 16 physical cores, that
is 32 logical CPUs and 32 stressors.

# Groups: the rule that changes everything

**A space separates two groups.** Everything else — commas, ranges, keywords — stays
inside the same group.

| Value | Effect |
|---|---|
| `selected_cpus=numa0 numa1` | two groups |
| `selected_cpus=numa0,1` | one group, the cpus of both domains merged |
| `selected_cpus=core0-3` | one group, the cpus of 4 physical cores merged |
| `selected_cpus=core0 core1` | two groups, one per physical core |

This matters because of a second rule: **a single group is flattened into a plain list of
logical CPUs**, and the default `iterate` scaling then walks that list *one CPU at a
time*. The same four physical cores therefore give two very different series.

One group, `selected_cpus=core0-3` — 8 benchmarks, one **logical cpu** each:

```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         1...............................................................  1
bench 1         .1..............................................................  1
bench 2         ..1.............................................................  1
bench 3         ...1............................................................  1
bench 4         2...............................................................  1
bench 5         .2..............................................................  1
bench 6         ..2.............................................................  1
bench 7         ...2............................................................  1
```

The group is flattened into the logical CPUs 0, 1, 2, 3, 64, 65, 66, 67, walked in that
order: first thread of each core, then second thread.

Four groups, `selected_cpus=core0 core1 core2 core3` — 4 benchmarks, one **physical
core** each, both threads loaded:

```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
bench 0         #...............................................................  2
bench 1         .#..............................................................  2
bench 2         ..#.............................................................  2
bench 3         ...#............................................................  2
```

Both are useful — the first measures a single thread, the second a full core with its
SMT siblings — but only one of them answers your question. When in doubt, run
[`uv run hwbench --dry-run`](#previewing-a-job-file---dry-run): it draws the effective pinning of
every benchmark on the target machine.

# selected_cpus_scaling: turning those CPUs into benchmarks

The iteration method over the CPUs listed by `selected_cpus`. Each step produces the
list of CPUs to test:

| Value | Effect |
|---|---|
| `iterate` | one benchmark per group, so as many benchmarks as groups (default) |
| `none` | one benchmark on the whole selection |
| `plus_<x>` | cumulative: `<x>` more groups at each step, so groups ÷ `<x>` benchmarks |
| `curve` | cumulative: 1, 2, 3, 4, 8, 16 then +16 groups, plus the end of each socket: a scaling curve |

## none: load everything at once

```ini
selected_cpus=all
selected_cpus_scaling=none
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
all_none_0      ################################################################  128
```

One benchmark, the whole machine. This is the "maximum performance" measurement.

`none` refuses a selection holding several groups — it would not know which one to keep —
and stops with
`Job <name>: keyword selected_cpus_scaling: none needs a single group of cpus, got several`.

## iterate: one benchmark per group

Used by every example above. Note that a selection holding a single item — one group
given by a helper, or one CPU — gives a single benchmark, whatever the configured value.

## plus_N: accumulate groups

```ini
selected_cpus=numa0 numa1 numa2 numa3
selected_cpus_scaling=plus_2
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
plus2_0         ################................................................  32
plus2_1         ################################................................  64
```

Two groups are added at each step, so 4 groups give 2 benchmarks. The number of groups
must be a multiple of `<x>`, otherwise the run stops with
`Job <name>: keyword selected_cpus_scaling: plus_2 needs a multiple of 2 items, got 3`.

`plus_<x>` needs real groups: combined with a flattened selection such as `core0-3` or
`0-7`, the run stops with
`Job <name>: keyword selected_cpus_scaling: plus_2 needs groups to accumulate, like selected_cpus=each-core`.

## curve: a scaling curve

```ini
selected_cpus=each-core
selected_cpus_scaling=curve
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
curve_0         #...............................................................    2
curve_1         ##..............................................................    4
curve_2         ###.............................................................    6
curve_3         ####............................................................    8
curve_4         ########........................................................   16
curve_5         ################................................................   32
curve_6         ################################................................   64
curve_7         ################################################................   96
curve_8         ################################################################  128
```

`curve` accumulates the groups like `plus_<x>`, but with a varying step: 1, 2, 3, 4, 8,
16 groups, then 16 more at each step. Unlike the other scalings, it is **CPU specific by
nature**: its steps are chosen for the way a processor behaves as its cores get loaded,
so it is meant to be used with `each-core`. With `each-core`, that is a performance scaling
curve from one physical core to the whole CPU, with enough points at the low end to see
the single-thread and low-count behaviour, and not too many at the high end. Two steps
are always added:

- the last group, so the whole selection is always measured;
- the last group of each socket, so a full socket is measured before the next one is
  loaded: 18 on a dual-socket 36-core machine, 160 on a dual-socket 320-core one.

**Physical reality:** the low steps measure turbo behaviour on a mostly idle CPU; the
high steps measure the sustained all-core regime, where power and thermal limits take
over. The two regimes are precisely what the curve is for, and why the early points are
dense. With `each-core`, the steps are made of *physical* cores with both their SMT
threads, so the curve is not polluted by sibling threads appearing halfway. This replaces
the `simple` helper of older hwbench versions, which, unlike `curve`, stopped its +16 steps
at 256 cores: a job file still using it is rejected at startup with the line to write instead.

The number of steps depends on the core count: 9 on this 64-core CPU, 25 on a 320-core
one. Nothing prevents using `curve` with other groups, but its steps only make sense for
physical cores: with `each-numa`, 1, 2, 3, 4, 8 then 16 domains is not a meaningful
series — `plus_1` is the scaling for domains. Like `plus_<x>`, it needs real groups: a
flattened selection such as `0-31` stops the run with
`Job <name>: keyword selected_cpus_scaling: curve needs groups to accumulate, like selected_cpus=each-core`.

hwbench ships a sample job file doing it for every stress-ng module,
[`configs/curve-cpu.conf`](../configs/curve-cpu.conf):

```ini
[global]
runtime=120
monitor=all
engine=stressng
selected_cpus=each-core
selected_cpus_scaling=curve
stressor_range=auto
skip_method=wait
```

After an idle reference, each of its jobs — `avx`, `cpu`, `stream`, `memrate` and
`qsort` — walks the curve from one physical core to all of them, each step fully loaded:
on this 8534P, 9 steps per engine module parameter, 91 benchmarks and 3h 02m in all.
`configs/curve-numa.conf` asks the same question NUMA domain by NUMA domain, with
[`each-numa` and `plus_1`](#each-core-each-numa-each-quadrant).

# Helpers

A helper is a keyword that **generates the groups for you**, from the topology of the
machine. It exists because the interesting CPU series are always relative to the
hardware: "one step per NUMA domain", "each physical core". Writing them by hand means
editing the job file for every machine; a helper keeps the job portable.

## each-core, each-numa, each-quadrant

**Intent:** one step per item of the topology — each physical core, each NUMA domain,
each quadrant — whatever their number on the target machine.

**What they generate:** one group per item, equivalent to writing `core0 core1 … coreN`,
`numa0 numa1 … numaN` or `quadrant0 … quadrantN` by hand, without knowing N.

```ini
selected_cpus=each-numa
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
each_numa_0     ########........................................................  16
each_numa_1     ........########................................................  16
each_numa_2     ................########........................................  16
each_numa_3     ........................########................................  16
each_numa_4     ................................########........................  16
each_numa_5     ........................................########................  16
each_numa_6     ................................................########........  16
each_numa_7     ........................................................########  16
```

The group is the item, so the scaling keyword decides what is done with them; the values of `selected_cpus_scaling` with `each-numa`:

| Value | Effect |
|---|---|
| `iterate` | one per NUMA domain, each on its own — the map above |
| `plus_1` | the domains added one by one: 0, then 0-1, then 0-2… |
| `plus_2` | two more domains at each step |

With `plus_1`, the NUMA domains are added one by one, each step fully loading the domains
selected so far:

```ini
selected_cpus=each-numa
selected_cpus_scaling=plus_1
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
numa_plus_1_0   ########........................................................   16
numa_plus_1_1   ################................................................   32
numa_plus_1_2   ########################........................................   48
numa_plus_1_3   ################################................................   64
numa_plus_1_4   ########################################........................   80
numa_plus_1_5   ################################################................   96
numa_plus_1_6   ########################################################........  112
numa_plus_1_7   ################################################################  128
```

Each step adds a NUMA domain and its cores, so the curve shows how the performance
aggregates and the cost of crossing domains. The number of steps is the number of NUMA
domains: 8 here, one per L3 cache, 2 on a dual-socket machine with one domain per socket,
1 on a CPU with a single NUMA domain. To add the memory controllers one by one, use
`each-quadrant` instead, see [NUMA domains and quadrants](#numa-domains-and-quadrants). This replaces the `numa-simple` helper of older hwbench versions: a
job file still using it is rejected at startup with the line to write instead.

hwbench ships a sample job file doing it for every stress-ng module,
[`configs/curve-numa.conf`](../configs/curve-numa.conf):

```ini
[global]
runtime=120
monitor=all
engine=stressng
selected_cpus=each-numa
selected_cpus_scaling=plus_1
stressor_range=auto
skip_method=wait
```

After an idle reference, each of its jobs — `avx`, `cpu`, `stream`, `memrate` and
`qsort` — adds the NUMA domains one by one, each step fully loaded: on this 8534P, 8
steps per engine module parameter, 81 benchmarks and 2h 42m in all.
`configs/curve-cpu.conf` asks the same question core by core, with
[`curve`](#curve-a-scaling-curve).

`each-core` makes one benchmark per physical core, with all its threads:

```ini
selected_cpus=each-core
```
```
physical core   0       8       16      24      32      40      48      56    63  number of stressor instances
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
each_core_0     #...............................................................   2
each_core_1     .#..............................................................   2
each_core_2     ..#.............................................................   2
...
each_core_63    ...............................................................#   2
```

**Physical reality:** comparing the items of one level side by side shows the
asymmetries an aggregated measurement hides: a slow core, a NUMA domain further from its
memory, a quadrant hotter than the others. `each-core` builds its groups from the
physical cores the kernel reports, so it stays right whatever the numbering of the
logical cpus. It is also the most expensive of the three: 64 benchmarks here, 320 on a
dual-socket 320-core machine, per engine module parameter.

On a machine with a single item — one NUMA domain, one quadrant — the helper gives a
single group, hence a single benchmark on the whole item.

## Adding a helper

Helpers are deliberately easy to add: a helper is a Python function taking the hardware
and returning the groups as a string, and its name, added to the `HELPERS` list, is the
keyword. Something like "one step per socket", "one step per L3 cache, even without LLC as NUMA" or "only the second
thread of each core" is a few lines of code, and becomes available to every job file
without touching the parser.
See the implementation notes below.

# What it costs in time

The CPU selection is what usually decides the duration of a run, and it is easy to write
a line that means days. On the AMD EPYC 8534P used throughout this page, with
`runtime=120` and `stressor_range=auto`:

| `selected_cpus` + `selected_cpus_scaling` | `engine_module_parameter` | Benchmarks | Duration |
|---|---|---|---|
| `all` + `none` | `int64` | 1 | 2 min |
| `each-numa` + `plus_1` | `int64` | 8 | 16 min |
| `each-core` + `curve` | `int64` | 9 | 18 min |
| `core0-63` + `iterate` (one group, per-cpu sweep) | `int64` | 128 | 4 h 16 min |
| `core0-63` + `iterate` (one group, per-cpu sweep) | `int8,int16,int32,int64,int128` | 640 | 21 h 20 min |

The last line is the same sweep as the one above it, with 5 values in
`engine_module_parameter` instead of one: each value runs the whole sweep again, so
128 × 5 = 640 benchmarks.

Two habits avoid unpleasant surprises: prefer a helper to a hand-written per-CPU sweep
when a curve is enough, and always check the number of benchmarks and the duration of the
run before starting it — [`uv run hwbench --dry-run`](#previewing-a-job-file---dry-run) prints both
in a fraction of a second.

# Previewing a job file: --dry-run

`--dry-run` shows what a job file will really run **on the target machine**, without running
it:

```shell
uv run hwbench -j <job_file> --dry-run
```

It detects the CPU topology, validates the whole job file, expands it exactly as a real
run would, and prints one map per job. Nothing else happens: no tuning, no environment
dump, no BMC or PDU connection, no benchmark. It takes a fraction of a second and **does
not need root**, so it can be run by any user before booking a machine for hours.

For instance, this job file, `numa.conf`, runs one benchmark on each of the first two NUMA
domains:

```ini
[global]
runtime=60
engine=stressng
engine_module=cpu
engine_module_parameter=int64
stressor_range=auto

[numa_domains]
selected_cpus=numa0 numa1
```

On the AMD EPYC 8534P of this page, `uv run hwbench -j numa.conf --dry-run` prints:

```
map legend: one column per physical core
  #  all threads of the core are pinned
  1  only its first thread is pinned
  2  only its second thread is pinned
  .  the core is not pinned

AMD EPYC 8534P 64-Core Processor: 1 socket(s), 64 physical cores, 128 logical cpus, 8 NUMA domains, 4 quadrants
hwbench: 1 jobs, 2 benchmarks, ETA 0h 02m 00s

========================================================= [numa_domains] =========================================================
runtime = 2 benchmarks x 60s = 0h 02m 00s
monitor=none
stressor_range=auto
stressor_range_scaling=plus_1
selected_cpus=numa0 numa1
selected_cpus_scaling=iterate
skip_method=bypass
sync_start=none
engine=stressng
engine_module=cpu
engine_module_parameter=int64

physical core   0       8       16      24      32      40      48      56    63  stressors  engine/module/parameter  logical cpus
                |-------|-------|-------|-------|-------|-------|-------|------|
numa domain     0000000011111111222222223333333344444444555555556666666677777777
quadrant        0000000000000000111111111111111122222222222222223333333333333333
numa_domains_0  ########........................................................         16  stressng/cpu/int64       0-7, 64-71
numa_domains_1  ........########................................................         16  stressng/cpu/int64       8-15, 72-79
```

The legend comes first and only lists the glyphs the maps below really use, plus every
thread number on a CPU with SMT — the second thread is explained even when the maps only
pin the first one. `[...]` is listed when lines were cut. On a CPU without SMT, no thread
number appears.

Each job starts with a line of `=` carrying its name, so jobs stand apart even on a
machine with hundreds of cores. Then comes the **effective definition** of the job: its own keywords merged with
[`[global]`](configuration.md#file-format) and the defaults, exactly as hwbench records it
in the `config` section of `results.json` (`Config.to_dict()`), empty values left out.
Engine specific keywords such as `disks` are part of it; a keyword falling back to
another one, like `engine_module` to the engine name, is not shown, the
`engine/module/parameter` column of the map giving the resolved value.

The `runtime` line is the only one that differs from the job file: it gives the number
of benchmarks, the `runtime` of each one and the resulting duration of the job, in the
same format as the run ETA — `runtime = 2 benchmarks x 60s = 0h 02m 00s`. Fully skipped
benchmarks do not run, so they are left out of the duration and counted apart, like
`(1 skipped)`. The run summary gives the total duration but no end time, since the run
does not start now.

The map reads like the ones of this page, with
more columns:

| Column | Content |
|---|---|
| benchmark | the name hwbench will give it in its output and in `results.json` |
| map | one column per physical core, same glyphs as in [Reading the maps](#reading-the-maps); `-` on the whole line when the benchmark is not pinned |
| stressors | the number of stressor instances, `auto` already resolved |
| engine/module/parameter | what runs on those CPUs |
| logical cpus | the logical CPUs of the pinning, i.e. what is handed to `taskset -c` |

The benchmarks are listed in the order they will run, so the numbering and the
interleaving of the engine module parameters are the real ones. A `socket` ruler is added
on multi-socket machines, and when a line would not fit in the terminal the map is drawn
as one block per socket. In a socket block, a benchmark pinned on another socket gives an
empty line; a run of 4 or more of them keeps its first and last lines around a `[...]`
line. A benchmark that will be fully skipped, for instance a method the
CPU cannot run with `skip_method=bypass`, is marked `(skipped)`.

It is also a validator: any error a real run would report at startup — an unknown
keyword, an unavailable engine module parameter, a missing binary — is reported the same
way, with a non-zero exit code. The accepted engine module parameters depend on the tool
installed on the target machine, and for stress-ng even on how it was built: a stress-ng 0.17.06
lacking `float128` refuses `configs/curve-cpu.conf`, a 0.22.01 accepts it.

# Implementation notes

**Resolution.** `Config.get_selected_cpus()` in `hwbench/config/config.py` turns the
keyword value into groups, in a fixed order: `all` is replaced by the full cpu range,
then the helpers are expanded, then the `quadrant`/`numa`/`core` resources are replaced
by their cpu lists, and what remains is parsed by `Config.parse_range()`. Helpers are
substituted longest name first, so a shorter name cannot match inside a longer one. A final
regexp catches any resource keyword left unprocessed and makes it fatal, which is what
turns a typo into an error instead of an empty selection.

**Groups.** `parse_range()` returns a flat list when the value holds a single group, and
a list of lists when it holds several. Everything described in
[Groups](#groups-the-rule-that-changes-everything) follows from that single behaviour.

**Topology.** The resource keywords are resolved through the `CPU` object:
`get_peer_siblings()` for `core<x>` — hence both SMT threads —
`get_logical_cores_in_numa_domain()` for `numa<x>` and `get_cores_in_quadrant()` for
`quadrant<x>`. A resource that does not exist on the target machine is fatal.

**Scaling.** All the strategies are implemented by a single function, `scaling()` in
`hwbench/bench/scaling.py`, shared with `stressor_range_scaling`. It returns, for each
step, the indexes of the groups it takes: one with `iterate`, all of them with `none`,
the first ones with `plus_<x>` and `curve`, which adds the end of each socket found with
`CPU.get_socket()`. `SCALINGS` lists the values each keyword accepts. A single group
gives a single step, whatever the value. `Benchmarks.parse_jobs_config()` then pins each
benchmark on its step: a single group as written, or the merge of several. The
validator, `validate_selected_cpus_scaling()`, calls the same function with the groups
of the job, so an impossible scaling is reported at startup.

**Stressor counts.** For each pinning, `__schedule_benchmarks()` picks the stressor counts
of the job with the same `scaling()`, and `__schedule_benchmark()` loops over them for
each engine module parameter, which makes the stressor count the innermost dimension of
the expansion. `stressor_range` goes through `Config.parse_range()` like `selected_cpus`,
hence the identical `x` / `x-y` / `x,y,z` syntax. `auto` is resolved there, not at parse
time, because it needs the pinning of the benchmark being created: the count becomes
`len(pinned_cpu)`, and the `none` pinning is what triggers the
`stressor_range=auto but no pinned cpu` error.

**Helpers.** They live in `hwbench/config/config_helpers.py`, one function per helper,
taking the hardware and returning the groups as a space-separated string.
`get_selected_cpus()` looks the function up by name, mapping dashes to underscores
(`each-numa` → `each_numa`), so adding a helper means writing the function and adding
its name to `HELPERS`, the list of that module that both `get_selected_cpus()` and the
validator walk; a removed helper is listed in `REMOVED_HELPERS` with its replacement, and
the validator rejects it with that message. A helper describes groups: when it gives a single one, `get_selected_cpus()`
keeps it as a group instead of flattening it, so it is not walked one cpu at a time.
`each_core()`, `each_numa()` and `each_quadrant()` return one group per item of
`get_cores_by_socket()`, `get_logical_cores_in_numa_domain()` and `get_cores_in_quadrant()`.
Because a helper only receives the hardware, it can express anything the `CPU` object
knows about the topology.

**Dry run.** `dry_run()` in `hwbench/hwbench.py` is handled before the root check. It
builds a `CpuOnlyHardware` (`hwbench/environment/hardware.py`), which only runs the CPU
detection (`lscpu` and `numactl -H`) in a temporary directory, and a `Benchmarks` created
with `dry_run=True`, which never connects the monitoring. It then calls the real
`parse_jobs_config()` and hands the result to `render()` in `hwbench/bench/cpumap.py`.
The columns come from `CPU.get_cores_by_socket()`, one per physical core in socket
order; `hwbench/bench/test_cpumap.py` checks the exact output on the mocked 8534P.

**Validation.** `validate_selected_cpus()` in `hwbench/config/config_syntax.py` works by
subtraction: it removes the helpers and the resource keywords it knows from the string,
parses what is left as a range, and reports whatever remains as an unhandled value. A
keyword added to `get_selected_cpus()` must therefore be added to the validator as well,
or it will be rejected at startup.
