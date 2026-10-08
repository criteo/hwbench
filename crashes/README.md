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
into this branch, which only adds `crashes/` on top of it. Links to `main`
code are permalinks to commit `989e23e` of `criteo/hwbench`, because the same lines of
this branch hold different code.

New syntax is rejected on `main` simply because it does not exist there, which says
nothing about the underlying bug. So each new-syntax config was also tried with its
closest old-syntax equivalent, kept in [`main-equivalents/`](main-equivalents/).

## A. Introduced by PR #132

Short description of each issue. The behaviour on the PR and on `main` is in the
"Behaviour" table of the linked issue.

| File | Issue on the PR | Fix |
|------|-----------------|-----|
| [01](01_plus_placeholder_cpus.conf) | `selected_cpus_scaling=plus_<x>` is accepted and silently runs as a `curve` | [issue 1](#issue-1) |
| [02](02_plus_placeholder_stressors.conf) | `stressor_range_scaling=plus_<x>` is accepted and silently runs as a `curve` | [issue 1](#issue-1) |
| [03](03_plus_unicode_digit.conf) | `plus_²` gives Python's `int()` error instead of `unknown value` | [issue 1](#issue-1) |
| [04](04_empty_items_scaling_first.conf) | `IndexError` on a malformed `selected_cpus` when the scaling keyword is written first | [issue 2](#issue-2), [issue 4](#issue-4) |
| [06](06_empty_items_global.conf) | same, with the malformed `selected_cpus` inherited from `[global]` | [issue 2](#issue-2), [issue 4](#issue-4) |
| [07](07_empty_stressors_curve.conf) | `IndexError` while expanding an empty `stressor_range` with `curve` | [issue 2](#issue-2) |
| [09](09_empty_group_curve.conf) | `IndexError` on an empty cpu group with `curve` | [issue 3](#issue-3) |
| [12](12_each_numa_cpuless_node.conf) | `each-numa` / `each-quadrant` emit a bogus `['']` group on a CPU-less NUMA node (`TypeError` or `ValueError`) | [issue 5](#issue-5), [issue 7](#issue-7) |
| [15](15_removed_helper_hidden_simple.conf) | removed helper `simple` gives a generic error, not the migration message, when the scaling keyword is written first | [issue 4](#issue-4) |
| [16](16_removed_helper_hidden_numa_simple.conf) | same with `numa-simple`, with a confusing `Non-numeric range` error | [issue 4](#issue-4) |

The [12](12_each_numa_cpuless_node.conf) case needs a topology with a CPU-less node (CXL/HBM). It was reproduced with a
mocked `numactl -H` output where node 1 has no cpus and node 2 has cpus 4-7.

<a id="pre-existing"></a>
## B. Pre-existing on main (for later)

Same result on `main` and on the PR, so the PR did not introduce them.

| File | Config | Result on both branches | Root cause | Code on `main` | Code on the PR | Fix |
|------|--------|-------------------------|------------|----------------|---------------------|-----|
| [08_empty_stressors_plus1.conf](08_empty_stressors_plus1.conf) | `stressor_range=1-8-2` (parsed as `[]`), default scaling | no error, 0 benchmarks ([`main-equivalents/g`](main-equivalents/g_empty_stressors.conf)) | `parse_range` silently drops a 3-part range and `validate_stressor_range` accepts anything | [`config/config.py:289-293`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config.py#L289-L293), [`config/config_syntax.py:63-65`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_syntax.py#L63-L65), loop at [`bench/benchmarks.py:182`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L182) | [`config/config.py:292-297`](../hwbench/config/config.py#L292-L297), [`config/config_syntax.py:67-69`](../hwbench/config/config_syntax.py#L67-L69), [`bench/scaling.py:56`](../hwbench/bench/scaling.py#L56) | [issue 2](#issue-2) (on `main`: [B1](#fix-b1)) |
| [10_empty_group_iterate.conf](10_empty_group_iterate.conf) | `selected_cpus=0-3 7-4`, `iterate` | no error; 2nd benchmark has 0 cpus and 0 stressors | a reversed range gives an empty group and `validate_selected_cpus` accepts it | [`config/config.py:293`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config.py#L293), [`config/config_syntax.py:91-92`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_syntax.py#L91-L92), stressor count at [`bench/benchmarks.py:189`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L189) | [`config/config.py:296`](../hwbench/config/config.py#L296), [`config/config_syntax.py:101-102`](../hwbench/config/config_syntax.py#L101-L102), [`bench/benchmarks.py:150`](../hwbench/bench/benchmarks.py#L150) | [issue 3](#issue-3) (on `main`: [B2](#fix-b2)) |
| [11_empty_group_plus1.conf](11_empty_group_plus1.conf) | same, `plus_1` | no error; both benchmarks pin the same 4 cpus | same | merge at [`bench/benchmarks.py:130-136`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L130-L136) | merge at [`bench/benchmarks.py:103`](../hwbench/bench/benchmarks.py#L103) | [issue 3](#issue-3) (on `main`: [B2](#fix-b2)) |
| [13_overlapping_groups_plus2.conf](13_overlapping_groups_plus2.conf) | `selected_cpus=0-3 2-5`, `plus_2` | `pinned_cpu=[0,1,2,2,3,3,4,5]`: 6 distinct cpus, 8 stressors | merged groups are sorted but never de-duplicated | [`bench/benchmarks.py:130-136`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L130-L136) (append, then `sorted`), count at [`:189`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L189) | [`bench/benchmarks.py:103`](../hwbench/bench/benchmarks.py#L103), count at [`:150`](../hwbench/bench/benchmarks.py#L150) | [issue 6](#issue-6) (on `main`: [B3](#fix-b3)) |
| [14_overlapping_numa_quadrant.conf](14_overlapping_numa_quadrant.conf) | `numa0 quadrant0`, `plus_1` | step 2 pins 48 cpus of which 32 are distinct, 48 stressors | same | same as 13 | same as 13 | [issue 6](#issue-6) (on `main`: [B3](#fix-b3)) |

The "Fix" column links to the [suggested fixes](#fixes) below (written against
the PR head); B1-B4 are the same fixes as patches against `main`.

Related pre-existing weaknesses seen in group A:
- The root cause of [07](07_empty_stressors_curve.conf) and [09](09_empty_group_curve.conf) is the empty list or empty group above ([08](08_empty_stressors_plus1.conf), [10](10_empty_group_iterate.conf), [11](11_empty_group_plus1.conf)). The PR
  only adds a new `curve` path that crashes on it.
- On a topology with a CPU-less node, `numa-simple` on `main` skipped the last NUMA node
  and repeated an earlier group ([`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf): 2 benchmarks of 4 cpus, node 2
  never used). The loop over `range(get_numa_domains_count())` assumes node ids without
  gaps: `main` [`hwbench/config/config_helpers.py:44-45`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_helpers.py#L44-L45), inherited by `each-numa` at
  the PR: [`hwbench/config/config_helpers.py:29`](../hwbench/config/config_helpers.py#L29) (fix: [issue 7](#issue-7) on the PR, [B4](#fix-b4) on `main`), on top of the new
  empty group.

<a id="fixes"></a>
## Code locations and suggested fixes

One entry per distinct issue. Paths and line numbers are those of the PR head. The fixes
were applied and tested in scratch worktrees, see the validation section at the end.

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
### 2. Empty item list (configs [04](04_empty_items_scaling_first.conf), [06](06_empty_items_global.conf), [07](07_empty_stressors_curve.conf); introduced, root cause pre-existing: [08](08_empty_stressors_plus1.conf))

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
| [07](07_empty_stressors_curve.conf) | `stressor_range=1-8-2` with `curve` | validation passes, then `IndexError` while expanding | `curve` does not exist; the empty range itself is pre-existing, see [B](#pre-existing) |

Fix, in `scaling()` before the `count == 1` check:
```python
count = len(items)
if count == 0:
    raise ValueError("no items to scale")
```
Also fix the root cause in `parse_range`:
```python
ranges = item.split("-")
if len(ranges) != 2:
    h.fatal(f"Invalid range {item!r} in '{input}'")
```
This also fixes 08 (`stressor_range=1-8-2` scheduling 0 benchmarks).

<a id="issue-3"></a>
### 3. Empty cpu group (configs [09](09_empty_group_curve.conf), [10](10_empty_group_iterate.conf), [11](11_empty_group_plus1.conf); `curve` crash introduced, acceptance pre-existing)

Code: [`hwbench/bench/scaling.py:59-64`](../hwbench/bench/scaling.py#L59-L64), where `items[index][0]` and `items[index + 1][0]` fail
on `[]` (the `IndexError` in 09). The group gets there because
[`hwbench/config/config.py:296`](../hwbench/config/config.py#L296) builds `range(7, 5)` for a reversed range `7-4`, and
[`hwbench/config/config_syntax.py:101-102`](../hwbench/config/config_syntax.py#L101-L102) only checks that the overall result is
non-empty.

**Behaviour**

| Config | Setting | On the PR | On `main` |
|--------|---------|-----------|-----------|
| [09](09_empty_group_curve.conf) | `selected_cpus=0-3 7-4` with `curve` | `IndexError` traceback | `curve` does not exist; the empty group itself is pre-existing, see [B](#pre-existing) |

Fix, in `scaling()` once `groups` is known:
```python
if groups and any(not item for item in items):
    raise ValueError("empty group of cpus")
```
Better still, reject a reversed range in `parse_range`:
```python
if int(ranges[0]) > int(ranges[1]):
    h.fatal(f"Reversed range {item!r} in '{input}'")
```

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
(import `h` from `hwbench.utils`). For the id gap, which is pre-existing, iterate over the
real node ids instead of `range(count)`, for example through a
`CPU.get_numa_domain_ids()` that returns `sorted(self.numa.numa_domains)`.

<a id="issue-6"></a>
### 6. Overlapping groups keep duplicate cpus (configs [13](13_overlapping_groups_plus2.conf), [14](14_overlapping_numa_quadrant.conf); pre-existing)

Code: [`hwbench/bench/benchmarks.py:103`](../hwbench/bench/benchmarks.py#L103). The merge sorts but does not de-duplicate, and
line 150 (`stressor_count = len(pinned_cpu)`) then counts the duplicates.

Fix:
```python
pinned_cpu = sorted({cpu for item in items for cpu in (item if isinstance(item, list) else [item])})
```
Or reject overlapping groups in `validate_selected_cpus_scaling`.

<a id="issue-7"></a>
### 7. Skipped NUMA node on id gaps ([`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf); pre-existing)

Same loop as issue 5: [`hwbench/config/config_helpers.py:29`](../hwbench/config/config_helpers.py#L29). On `main` the equivalent
was the `numa-simple` helper. Fixed by iterating over the real node ids, as above.

## Fixes for the pre-existing issues, as patches against main

The fixes above are written against the PR head. The pre-existing issues also exist on
`main`, where the code has a different shape, so here are the equivalent fixes there.
Tested in a scratch worktree of `main`, see the validation section. Each one is scoped to the validation of the keyword concerned,
because `parse_range` is also used for `engine_module_parameter` values, which may
contain dashes.

<a id="fix-b1"></a>
### B1. Empty `stressor_range` (config [08](08_empty_stressors_plus1.conf); `main` [`config/config_syntax.py:63-65`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_syntax.py#L63-L65))

`validate_stressor_range` accepts anything, and `parse_range` returns `[]` for `1-8-2`.

```python
def validate_stressor_range(config, section_name, value) -> str:
    """Validate the stressor range syntax."""
    if not config.parse_range(value):
        return f"'{value}' is not a valid stressor range (expected x, x-y or x,y,z)"
    return ""
```

<a id="fix-b2"></a>
### B2. Reversed range gives an empty cpu group (configs [10](10_empty_group_iterate.conf), [11](11_empty_group_plus1.conf); `main` [`config/config.py:289-293`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config.py#L289-L293))

`range(7, 5)` is empty, and `validate_selected_cpus` ([`config/config_syntax.py:91-92`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_syntax.py#L91-L92))
only checks that the overall result is not empty. A reversed range is never valid, so
reject it where it is parsed:

```python
if len(ranges) == 2:
    if not ranges[0].isnumeric() or not ranges[1].isnumeric():
        h.fatal(f"Non-numeric range {ranges} in '{input}'")
    if int(ranges[0]) > int(ranges[1]):
        h.fatal(f"Reversed range {item!r} in '{input}'")
```

<a id="fix-b3"></a>
### B3. Overlapping groups keep duplicate cpus (configs [13](13_overlapping_groups_plus2.conf), [14](14_overlapping_numa_quadrant.conf); `main` [`bench/benchmarks.py:130-136`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L130-L136))

The `plus_<x>` branch accumulates cpus with `pinned_cpu.append(cpu)` and passes
`sorted(pinned_cpu.copy())`. Use a set at that call, and in the `none` branch too
([`bench/benchmarks.py:148`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/bench/benchmarks.py#L148)), where `sorted(selected_cpus)` keeps duplicates from a flat
`selected_cpus=0-3,2-5`:

```python
self.__schedule_benchmarks(
    job,
    stressor_range_scaling,
    sorted(set(pinned_cpu)),
    validate_parameters,
)
```

<a id="fix-b4"></a>
### B4. NUMA node skipped on id gaps ([`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf); `main` [`config/config_helpers.py:42-47`](https://github.com/criteo/hwbench/blob/989e23e3c7a6c16348ed07ecbaed56f3b3dcaa9b/hwbench/config/config_helpers.py#L42-L47))

`numa_simple` loops over `range(cpu.get_numa_domains_count())`. With node ids `{0, 2}`,
it visits 0 and 1: node 1 adds nothing, so the same group is emitted twice, and node 2
is never reached. Iterate over the real ids and skip nodes without cpus:

```python
for numa_domain in sorted(cpu.numa.numa_domains):
    node_cores = cpu.get_logical_cores_in_numa_domain(numa_domain)
    if not node_cores:
        continue
    cores += node_cores
    groups.append(",".join(str(core) for core in sorted(cores)))
```

`numa_simple` no longer exists on the PR; the same loop shape is in `each_numa` and
`each_quadrant` ([`config_helpers.py:29`](../hwbench/config/config_helpers.py#L29), [`:35`](../hwbench/config/config_helpers.py#L35)), covered by [issue 5](#issue-5) and [issue 7](#issue-7) above.

## Controls (not issues)

| File | Purpose |
|------|---------|
| [05_empty_items_selected_first_CONTROL.conf](05_empty_items_selected_first_CONTROL.conf) | 04 with the keywords swapped: clean `Unhandled string '1-2-3'` |
| [17_removed_helper_CONTROL.conf](17_removed_helper_CONTROL.conf) | 15 with the keywords swapped: clean `simple was removed, use ...` |

## Review findings without a config

- `cpu_list_to_range` sorting its argument in place, and the removed graph code and
  `pyyaml` dependency. They came from reviewing a copy of the branch that was behind
  `main`. Against the PR head, [`hwbench/utils/helpers.py`](../hwbench/utils/helpers.py) only gains
  `format_duration` and [`graph/`](../graph) is unchanged, so they do not apply.
- Stale `simple` in the leftover-keyword regex of `get_selected_cpus`: maintainability
  only, no config changes behaviour because of it.

## main-equivalents/

Old-syntax versions of the configs above, each with a `# Run on main:` header giving the
result on `main`. [`d_numa_simple_cpuless.conf`](main-equivalents/d_numa_simple_cpuless.conf) and [`e_explicit_quadrant_cpuless.conf`](main-equivalents/e_explicit_quadrant_cpuless.conf) need
the CPU-less topology of file 12.

## Validation of the code links and fixes

Checked against this branch, whose code is identical to the PR head (it only adds
`crashes/`), and against `main` for the `main` references.

- **Code links:** every `file:line` reference was printed from `git show <branch>:<file>`
  and matches the code it describes.
- **Fixes 1-7 (PR head):** applied together in a scratch worktree. The existing
  suite still passes (102 tests, same as before the fixes) and every config in this
  directory then gives a clean error, or a correct result for the ones that should run:
  - [01](01_plus_placeholder_cpus.conf)-[03](03_plus_unicode_digit.conf), [15](15_removed_helper_hidden_simple.conf), [16](16_removed_helper_hidden_numa_simple.conf): `unknown value ...` and the `... was removed, use ...` message.
  - [04](04_empty_items_scaling_first.conf), [06](06_empty_items_global.conf)-[11](11_empty_group_plus1.conf): a clean fatal. The `scaling()` guards (`no items to scale`,
    `empty group of cpus`) also work on their own, without the `parse_range` change.
  - [12](12_each_numa_cpuless_node.conf): `[[0, 1, 2, 3], [4, 5, 6, 7]]` for both `each-numa` and `each-quadrant`, and the
    job runs.
  - [13](13_overlapping_groups_plus2.conf), [14](14_overlapping_numa_quadrant.conf): 6 and 32 distinct cpus, with matching stressor counts.
- **Fixes B1-B4 (`main`):** applied in a scratch worktree of `main`. The suite still
  passes (70 tests). [08](08_empty_stressors_plus1.conf) and [`main-equivalents/g`](main-equivalents/g_empty_stressors.conf) give the `not a valid stressor range`
  error, [10](10_empty_group_iterate.conf) and [11](11_empty_group_plus1.conf) give `Reversed range '7-4'`, [13](13_overlapping_groups_plus2.conf) and [14](14_overlapping_numa_quadrant.conf) pin 6 and 32 distinct cpus, and
  [`main-equivalents/d`](main-equivalents/d_numa_simple_cpuless.conf) now uses node 2 (2 benchmarks of 4 and 8 cpus).
- **Side effect on the controls:** with the `parse_range` change of issue 2, 05 reports
  `Invalid range '1-2-3'` instead of `Unhandled string '1-2-3'`. Without it, 05 keeps its
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
