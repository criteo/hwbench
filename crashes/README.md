# Configs that crash or misbehave in PR #132

Reproducers for the problems found in the reviews of [PR #132](https://github.com/criteo/hwbench/pull/132) (head `f42a508`),
merged so there is one row per config. Each file starts with a `# Status:` line, then the
expected and the actual behaviour. The configs use the new syntax (`each-*`, `curve`), so
they only run on the PR.

## How this was checked

Every config was run on the PR head (`f42a508`) and on `main` through the repo's
mocked-hardware harness (`load_mocked_hardware`: 64-core/128-thread AMD, 8 NUMA
domains), calling `Benchmarks.parse_jobs_config()`. They were also run with the real
`hwbench --dry-run` on an 8-cpu host without NUMA, with the same kinds of result. Two
cases depend on the topology there: 12 fails with `ValueError` `int('')` because no NUMA
domain is detected, and 14 fails with `NUMA domain 0 does not exists`.

Line numbers are those of the PR head (`f42a508`). Links to that code are relative links
into this branch, which only adds `crashes/` on top of it.

Where the old syntax has an equivalent of a config, the equivalent was also run on `main`,
to tell the issues the PR introduced from the ones already there. They are kept in [`main-equivalents/`](main-equivalents/).

# A. Introduced by PR #132

Short description of each issue. The behaviour on the PR and on `main` is in the
"Behaviour" table of the linked issue, in the details at the end.

| File | Issue on the PR | Fix |
|------|-----------------|-----|
| [01](01_plus_placeholder_cpus.conf) | `selected_cpus_scaling=plus_<x>` is accepted and silently runs as a `curve` | [issue 1](#issue-1) |
| [02](02_plus_placeholder_stressors.conf) | `stressor_range_scaling=plus_<x>` is accepted and silently runs as a `curve` | [issue 1](#issue-1) |
| [03](03_plus_unicode_digit.conf) | `plus_²` gives Python's `int()` error instead of `unknown value` | [issue 1](#issue-1) |
| [04](04_empty_items_scaling_first.conf) | `IndexError` on a malformed `selected_cpus` when the scaling keyword is written first | [issue 2](#issue-2), [issue 4](#issue-4) |
| [06](06_empty_items_global.conf) | same, with the malformed `selected_cpus` inherited from `[global]` | [issue 2](#issue-2), [issue 4](#issue-4) |
| [07](07_empty_stressors_curve.conf) | `IndexError` while expanding an empty `stressor_range` with `curve` | [issue 2](#issue-2) |
| [09](09_empty_group_curve.conf) | `IndexError` on an empty cpu group with `curve` | [issue 3](#issue-3) |
| [12](12_each_numa_cpuless_node.conf) | `each-numa` / `each-quadrant` emit a bogus `['']` group on a CPU-less NUMA node (`TypeError` or `ValueError`) | [issue 5](#issue-5), [P4](#pre-4) |
| [15](15_removed_helper_hidden_simple.conf) | removed helper `simple` gives a generic error, not the migration message, when the scaling keyword is written first | [issue 4](#issue-4) |
| [16](16_removed_helper_hidden_numa_simple.conf) | same with `numa-simple`, with a confusing `Non-numeric range` error | [issue 4](#issue-4) |

The [12](12_each_numa_cpuless_node.conf) case needs a topology with a CPU-less node (CXL/HBM). It was reproduced with a
mocked `numactl -H` output where node 1 has no cpus and node 2 has cpus 4-7.

## Controls (not issues)

| File | Purpose |
|------|---------|
| [05_empty_items_selected_first_CONTROL.conf](05_empty_items_selected_first_CONTROL.conf) | 04 with the keywords swapped: clean `Unhandled string '1-2-3'` |
| [17_removed_helper_CONTROL.conf](17_removed_helper_CONTROL.conf) | 15 with the keywords swapped: clean `simple was removed, use ...` |

<a id="fixes"></a>
## Details of the issues introduced by the PR

Paths and line numbers are those of the PR head. The fixes were applied and tested in scratch
worktrees, see the validation section at the end.

<a id="issue-1"></a>
### 1. `plus_<x>` placeholder and `plus_²` accepted (configs [01](01_plus_placeholder_cpus.conf), [02](02_plus_placeholder_stressors.conf), [03](03_plus_unicode_digit.conf); introduced)

Code: [`hwbench/bench/scaling.py:34-37`](../hwbench/bench/scaling.py#L34-L37). The lookup uses `value` itself when `is_plus` is
False, and `"plus_<x>"` is an entry of `SCALINGS`. `isnumeric()` on line 35 also accepts
`²`, which `int()` rejects.

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [01](01_plus_placeholder_cpus.conf) | `selected_cpus_scaling=plus_<x>` | no error, silently runs as `curve` (9 benchmarks) | `ValueError` traceback ([`main-equivalents/a`](main-equivalents/a_plus_placeholder_groups.conf)). The validation gap existed, the symptom changed |
| [02](02_plus_placeholder_stressors.conf) | `stressor_range_scaling=plus_<x>` | no error, silently runs as `curve` (stressors 1,2,3,4,8,16,32,48,64) | clean `Unsupported stressor_range_scaling : plus_<x>` |
| [03](03_plus_unicode_digit.conf) | `stressor_range_scaling=plus_²` | clean fatal, but with Python's `invalid literal for int() with base 10: '²'` | clean `Unsupported stressor_range_scaling : plus_²` (with groups it crashed, [`main-equivalents/b`](main-equivalents/b_plus_unicode_groups.conf)) |

Fix:
```python
increment = value.replace("plus_", "", 1)
is_plus = value.startswith("plus_") and increment.isdecimal() and int(increment) > 0
if is_plus:
    known = "plus_<x>" in SCALINGS[keyword]
else:
    known = value in SCALINGS[keyword] and value != "plus_<x>"
if not known:
    raise ValueError(f"unknown value {value}")
```
Add `plus_<x>` and `plus_²` to the cases of `test_impossible_scalings`.

<a id="issue-2"></a>
### 2. Empty item list (configs [04](04_empty_items_scaling_first.conf), [06](06_empty_items_global.conf), [07](07_empty_stressors_curve.conf); introduced; the empty list itself is pre-existing, see [P1](#pre-1))

Code: [`hwbench/bench/scaling.py:42`](../hwbench/bench/scaling.py#L42) (`items[0]` on an empty list) and [`scaling.py:39-41`](../hwbench/bench/scaling.py#L39-L41).
For a stressor `curve`, `count` ends up in `steps`, which gives `[[]]`, and
[`hwbench/bench/benchmarks.py:118`](../hwbench/bench/benchmarks.py#L118) (`stressor_range[step[-1]]`) then fails.
Root cause: [`hwbench/config/config.py:292-297`](../hwbench/config/config.py#L292-L297), where `parse_range` silently drops an item
containing `-` that does not split into 2 parts, such as `1-2-3`.

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [04](04_empty_items_scaling_first.conf) | `selected_cpus_scaling` before `selected_cpus=1-2-3` | `IndexError` traceback | clean `Unhandled string '1-2-3'` ([`main-equivalents/c`](main-equivalents/c_scaling_first_bad_cpus.conf)) |
| [06](06_empty_items_global.conf) | bad `selected_cpus` inherited from `[global]` | `IndexError` traceback | clean error, as above |
| [07](07_empty_stressors_curve.conf) | `stressor_range=1-8-2` with `curve` | validation passes, then `IndexError` while expanding | — |

Fix, in `scaling()` before the `count == 1` check:
```python
count = len(items)
if count == 0:
    raise ValueError("no items to scale")
```
The root cause, `parse_range` silently dropping `1-2-3`, is pre-existing: see [P1](#pre-1) for its fix.

<a id="issue-3"></a>
### 3. Empty cpu group (config [09](09_empty_group_curve.conf); the `curve` crash is introduced, the empty group itself is pre-existing, see [P2](#pre-2))

Code: [`hwbench/bench/scaling.py:59-64`](../hwbench/bench/scaling.py#L59-L64), where `items[index][0]` and `items[index + 1][0]` fail
on `[]` (the `IndexError` in 09). The group gets there because
[`hwbench/config/config.py:296`](../hwbench/config/config.py#L296) builds `range(7, 5)` for a reversed range `7-4`, and
[`hwbench/config/config_syntax.py:101-102`](../hwbench/config/config_syntax.py#L101-L102) only checks that the overall result is
non-empty.

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [09](09_empty_group_curve.conf) | `selected_cpus=0-3 7-4` with `curve` | `IndexError` traceback | — |

Fix, in `scaling()` once `groups` is known:
```python
if groups and any(not item for item in items):
    raise ValueError("empty group of cpus")
```
Better still, reject the reversed range where it is parsed, see [P2](#pre-2).

<a id="issue-4"></a>
### 4. Validation order depends on keyword order (configs [04](04_empty_items_scaling_first.conf), [06](06_empty_items_global.conf), [15](15_removed_helper_hidden_simple.conf), [16](16_removed_helper_hidden_numa_simple.conf); introduced)

Code: [`hwbench/config/config_syntax.py:111-119`](../hwbench/config/config_syntax.py#L111-L119) (and the same pattern at `72-77` for
`validate_stressor_range_scaling`). The scaling validator calls
`config.get_selected_cpus()` before `validate_selected_cpus` has checked the value, and
`validate_section` visits keys in file order ([`hwbench/config/config.py:250`](../hwbench/config/config.py#L250)).

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [15](15_removed_helper_hidden_simple.conf) | scaling keyword before `selected_cpus=simple` | generic `didn't get processed ! : ['simple']`; the migration message is never shown | `simple` still worked |
| [16](16_removed_helper_hidden_numa_simple.conf) | same with `numa-simple` | confusing `Non-numeric range ['', ''] in '-'` | `numa-simple` still worked |

[04](04_empty_items_scaling_first.conf) and [06](06_empty_items_global.conf) show the same ordering dependency, see [issue 2](#issue-2).

Fix, in `validate_selected_cpus_scaling`:
```python
message = validate_selected_cpus(config, section_name, config.get_section(section_name)["selected_cpus"])
if message:
    return message
```
Alternatively, make `validate_section` validate `selected_cpus` and `stressor_range`
before their `*_scaling` keywords. The stale `simple` in the regex at
[`hwbench/config/config.py:208`](../hwbench/config/config.py#L208) can go at the same time.

<a id="issue-5"></a>
### 5. Empty groups from `each-numa` / `each-quadrant` (config [12](12_each_numa_cpuless_node.conf); introduced)

Code: [`hwbench/config/config_helpers.py:14-16`](../hwbench/config/config_helpers.py#L14-L16) (`groups()` keeps empty lists, which become a
double space and then the group `['']`), [`config_helpers.py:29`](../hwbench/config/config_helpers.py#L29) and [`config_helpers.py:35`](../hwbench/config/config_helpers.py#L35) (loops over
`range(count)` of ids). [`hwbench/environment/numa.py:21`](../hwbench/environment/numa.py#L21) only records nodes whose line
matches `cpus: ...`, so a CPU-less node leaves a gap in the ids.

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [12](12_each_numa_cpuless_node.conf) | `each-numa` / `each-quadrant` with a CPU-less NUMA node | helpers give a bogus `['']` group: `TypeError` in `sorted()` with `plus_1`, `ValueError` `int('')` with `iterate` | `numa-simple` did not crash ([`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf)) and an explicit `quadrant1` failed cleanly with `Quadrant 1 does not exists` ([`main-equivalents/e`](main-equivalents/e_explicit_quadrant_cpuless.conf)). The helpers lost that guard |

Fix:
```python
def groups(cpu_lists):
    non_empty = [cpus for cpus in cpu_lists if cpus]
    if not non_empty:
        h.fatal("selected_cpus helper: no group with cpus found")
    return " ".join(",".join(str(cpu) for cpu in sorted(cpus)) for cpus in non_empty)
```
(import `h` from `hwbench.utils`). The id gap, which is pre-existing, is covered by [P4](#pre-4).

<a id="pre-existing"></a>
# B. Pre-existing on main

Same result on `main` and on the PR, so the PR did not introduce them. The behaviour,
the code and the suggested fixes are in the [details at the end](#pre-existing-details).

| File | Issue | Fix |
|------|-------|-----|
| [08](08_empty_stressors_plus1.conf) | `stressor_range=1-8-2` (not a valid range) is accepted and schedules 0 benchmarks | [P1](#pre-1) |
| [10](10_empty_group_iterate.conf) | reversed range `7-4` gives an empty cpu group, accepted with `iterate`: a benchmark with 0 cpus and 0 stressors | [P2](#pre-2) |
| [11](11_empty_group_plus1.conf) | same, with `plus_1`: two benchmarks pin the same cpus | [P2](#pre-2) |
| [13](13_overlapping_groups_plus2.conf) | overlapping groups (`0-3 2-5`) merged by `plus_2` keep their duplicate cpus: 8 stressors for 6 cpus | [P3](#pre-3) |
| [14](14_overlapping_numa_quadrant.conf) | overlapping `numa0 quadrant0` merged by `plus_1` keep their duplicate cpus | [P3](#pre-3) |
| [`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf), [12](12_each_numa_cpuless_node.conf) | on a topology with a CPU-less NUMA node, the NUMA node after the id gap is never selected | [P4](#pre-4) |

The patches are written on top of the PR, with the fixes of the introduced issues applied:
P1 and P2 are already resolved by those fixes, and only P3 and P4 need a patch of their own.

<a id="pre-existing-details"></a>
## Details of the pre-existing issues

The configs give the same result on `main` and on the PR. As the PR is going to be merged
and the issues it introduces fixed, the suggested patches are written on top of the PR
head, with the fixes of the [issues above](#fixes) applied. Two of the four are already
resolved by those fixes.

<a id="pre-1"></a>
### P1. Empty `stressor_range` (config [08](08_empty_stressors_plus1.conf))

`stressor_range=1-8-2` is not a valid range, but `parse_range` silently drops an item with
`-` that does not split into 2 parts and returns `[]`, and `validate_stressor_range`
accepts anything. The job then schedules 0 benchmarks, without any error, and is missing
from the dry-run map. The same config in old syntax is [`main-equivalents/g`](main-equivalents/g_empty_stressors.conf).

**Behaviour** (same on `main` and on the PR)

| Config | Setting | Result |
|--------|---------|--------|
| [08](08_empty_stressors_plus1.conf) | `stressor_range=1-8-2`, default scaling | no error, 0 benchmarks |

**Code**: [`hwbench/config/config.py:292-297`](../hwbench/config/config.py#L292-L297) (`parse_range`), [`hwbench/config/config_syntax.py:67-69`](../hwbench/config/config_syntax.py#L67-L69) (`validate_stressor_range`), [`hwbench/bench/scaling.py:56`](../hwbench/bench/scaling.py#L56).

**Fix**: none needed on top of the [issue 2](#issue-2) fix. Its `count == 0` guard in
`scaling()` makes the job fail with `no items to scale` (checked). For a clearer message,
`parse_range` can also reject the range:
```python
ranges = item.split("-")
if len(ranges) != 2:
    h.fatal(f"Invalid range {item!r} in '{input}'")
```

<a id="pre-2"></a>
### P2. Reversed range gives an empty cpu group (configs [10](10_empty_group_iterate.conf), [11](11_empty_group_plus1.conf))

`7-4` builds `range(7, 5)`, which is empty, so the group is `[]`. `validate_selected_cpus` only
checks that the overall result is not empty, so it accepts it. With `iterate` a step pins
on `[]`; with the stressng engine and `stressor_range=auto` that benchmark has 0 stressors,
and as `get_taskset` adds no `taskset` for an empty pinning and `stress-ng --cpu 0` starts one
worker per online cpu, it loads the whole machine (checked with stress-ng 0.19.02).

**Behaviour** (same on `main` and on the PR)

| Config | Setting | Result |
|--------|---------|--------|
| [10](10_empty_group_iterate.conf) | `selected_cpus=0-3 7-4`, `iterate` | no error; the 2nd benchmark has 0 cpus and 0 stressors |
| [11](11_empty_group_plus1.conf) | same, `plus_1` | no error; both benchmarks pin the same 4 cpus |

**Code**: [`hwbench/config/config.py:296`](../hwbench/config/config.py#L296) (`parse_range`), [`hwbench/config/config_syntax.py:101-102`](../hwbench/config/config_syntax.py#L101-L102) (`validate_selected_cpus`), stressor count at [`hwbench/bench/benchmarks.py:150`](../hwbench/bench/benchmarks.py#L150), merge at [`hwbench/bench/benchmarks.py:103`](../hwbench/bench/benchmarks.py#L103).

**Fix**: none needed on top of the [issue 3](#issue-3) fix. Its `empty group of cpus`
guard in `scaling()` makes both jobs fail cleanly (checked). For the error to name the
reversed range, `parse_range` can also reject it:
```python
if int(ranges[0]) > int(ranges[1]):
    h.fatal(f"Reversed range {item!r} in '{input}'")
```

<a id="pre-3"></a>
### P3. Overlapping groups keep duplicate cpus (configs [13](13_overlapping_groups_plus2.conf), [14](14_overlapping_numa_quadrant.conf))

When a step merges several groups, the cpus are sorted but never de-duplicated, so groups
that overlap, such as `0-3 2-5` or `numa0 quadrant0`, pin some cpus twice. With
`stressor_range=auto` the stressor count is `len(pinned_cpu)`, so more stressors start than
there are distinct cpus. Not fixed by the fixes of the introduced issues (checked).

**Behaviour** (same on `main` and on the PR)

| Config | Setting | Result |
|--------|---------|--------|
| [13](13_overlapping_groups_plus2.conf) | `selected_cpus=0-3 2-5`, `plus_2` | `pinned_cpu=[0,1,2,2,3,3,4,5]`: 6 distinct cpus, 8 stressors |
| [14](14_overlapping_numa_quadrant.conf) | `numa0 quadrant0`, `plus_1` | step 2 pins 48 cpus of which 32 are distinct, 48 stressors |

**Code**: [`hwbench/bench/benchmarks.py:103`](../hwbench/bench/benchmarks.py#L103) (the merge), count at [`hwbench/bench/benchmarks.py:150`](../hwbench/bench/benchmarks.py#L150).

**Fix**, a set in the merge, which also covers a flat `selected_cpus=0-3,2-5` with the `none`
scaling since it is merged on the same line (or reject overlapping groups in
`validate_selected_cpus_scaling`):
```python
pinned_cpu = sorted({cpu for item in items for cpu in (item if isinstance(item, list) else [item])})
```

<a id="pre-4"></a>
### P4. NUMA node skipped on id gaps (config [12](12_each_numa_cpuless_node.conf))

On a topology with a CPU-less NUMA node, the node ids have a gap, for example `{0, 2}`,
because `numactl -H` only gives a `cpus:` line to nodes with cpus. `each_numa` loops over
`range(get_numa_domains_count())`, so it visits ids 0 and 1 and node 2 is never selected,
silently. The same gap already existed on `main` in `numa-simple` ([`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf): 2 benchmarks of
4 cpus, node 2 never used). It remains once the empty group of [issue 5](#issue-5) is fixed.

**Behaviour** (config [12](12_each_numa_cpuless_node.conf) on a topology where node 1 has no cpus and node 2 has cpus 4-7)

| Setting | Result with the fixes of the introduced issues |
|---------|------------------------------------------------|
| `each-numa`, `plus_1` | 1 benchmark, node 0 only; node 2 is never selected |

**Code**: [`hwbench/config/config_helpers.py:29`](../hwbench/config/config_helpers.py#L29) (`each_numa`), [`hwbench/environment/numa.py:21`](../hwbench/environment/numa.py#L21) (only nodes with a `cpus:` line are recorded).

**Fix**, on top of the `groups()` fix of [issue 5](#issue-5): iterate over the real node
ids, through a new `CPU.get_numa_domain_ids()` that returns `sorted(self.numa.numa_domains)`:
```python
groups([cpu.get_logical_cores_in_numa_domain(domain) for domain in cpu.get_numa_domain_ids()])
```

## Validation of the code links and fixes

Checked against this branch, whose code is identical to the PR head (it only adds
`crashes/`).

- **Code links:** every `file:line` reference was printed from `git show <branch>:<file>`
  and matches the code it describes.
- **Fixes of issues 1-5:** applied together in a scratch worktree. The existing suite still
  passes (102 tests, same as before the fixes) and every config in this directory then
  gives a clean error, or a correct result for the ones that should run:
  - [01](01_plus_placeholder_cpus.conf)-[03](03_plus_unicode_digit.conf), [15](15_removed_helper_hidden_simple.conf), [16](16_removed_helper_hidden_numa_simple.conf): `unknown value ...` and the `... was removed, use ...` message.
  - [04](04_empty_items_scaling_first.conf), [06](06_empty_items_global.conf)-[11](11_empty_group_plus1.conf): a clean fatal. The `scaling()` guards (`no items to scale`,
    `empty group of cpus`) work on their own, without the `parse_range` change, and so
    resolve the pre-existing [08](08_empty_stressors_plus1.conf), [10](10_empty_group_iterate.conf) and [11](11_empty_group_plus1.conf) (P1, P2).
  - [12](12_each_numa_cpuless_node.conf): `each-quadrant` gives `[[0, 1, 2, 3], [4, 5, 6, 7]]`, but `each-numa` gives only node 0 (P4).
  - [13](13_overlapping_groups_plus2.conf), [14](14_overlapping_numa_quadrant.conf): unchanged, still 8 and 48 stressors for 6 and 32 distinct cpus (P3).
- **Patches of P3 and P4, on top of that:** the suite still passes (102 tests), [13](13_overlapping_groups_plus2.conf) and
  [14](14_overlapping_numa_quadrant.conf) pin 6 and 32 distinct cpus with matching stressor counts, and [12](12_each_numa_cpuless_node.conf) gives
  `each-numa` groups of 4 and 8 cpus.
- **Optional `parse_range` checks** (P1, P2): with them, [05](05_empty_items_selected_first_CONTROL.conf) reports
  `Invalid range '1-2-3'` instead of `Unhandled string '1-2-3'`. Without them, 05 keeps its
  original message.
- **stress-ng with a count of 0 (config [10](10_empty_group_iterate.conf)):** checked with stress-ng 0.19.02 installed on
  the host. `stress-ng --cpu 0 --timeout 1` dispatched 8 cpu hogs on the 8-cpu host, so a
  count of 0 means one stressor per online cpu. `get_taskset`
  ([`hwbench/bench/benchmark.py:93-103`](../hwbench/bench/benchmark.py#L93-L103)) adds no `taskset` prefix for an empty pinned list,
  so the second benchmark of config 10 would load every cpu, unpinned, instead of the
  intended cores. This was checked by reading the code and running stress-ng directly, not
  by running hwbench end to end.
- **Before the fixes:** the 17 configs were re-run on an unmodified checkout of
  this branch and gave the results listed in the tables above.
