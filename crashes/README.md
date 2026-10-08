# Configs that crash or misbehave on pr-132-up

Reproducers for the problems found in the reviews of `main..pr-132-up`
(`pr-132.json`, `pr-132-2.json` ... `pr-132-7.json`), merged so there is one row per
config. Each file starts with a `# Status:` line, then the expected and the actual
behaviour. The configs use the new syntax (`each-*`, `curve`), so they only run on
`pr-132-up`.

## How this was checked

Every config was run on `pr-132-up` (f42a508) and on `main` through the repo's
mocked-hardware harness (`load_mocked_hardware`: 64-core/128-thread AMD, 8 NUMA
domains), calling `Benchmarks.parse_jobs_config()`. The real `hwbench --dry-run` could not
be used on the host that ran this, because `numactl` and `stress-ng` are not installed.
Line numbers are those of the `pr-132-up` files.

New syntax is rejected on `main` simply because it does not exist there, which says
nothing about the underlying bug. So each new-syntax config was also tried with its
closest old-syntax equivalent, kept in [`main-equivalents/`](main-equivalents/).

## A. Introduced by pr-132

| File | Config | On `pr-132-up` | On `main` |
|------|--------|----------------|-----------|
| 01_plus_placeholder_cpus.conf | `selected_cpus_scaling=plus_<x>` (`scaling.py:35-37`) | no error, silently runs as `curve` (9 benchmarks) | `ValueError` traceback (`main-equivalents/a`). The validation gap existed, the symptom changed |
| 02_plus_placeholder_stressors.conf | `stressor_range_scaling=plus_<x>` (`scaling.py:35-37`) | no error, silently runs as `curve` (stressors 1,2,3,4,8,16,32,48,64) | clean `Unsupported stressor_range_scaling : plus_<x>` |
| 03_plus_unicode_digit.conf | `stressor_range_scaling=plus_²` (`scaling.py:35`) | clean fatal, but with Python's `invalid literal for int() with base 10: '²'` | clean `Unsupported stressor_range_scaling : plus_²` (with groups it crashed, `main-equivalents/b`) |
| 04_empty_items_scaling_first.conf | `selected_cpus_scaling` before `selected_cpus=1-2-3` (`scaling.py:42`) | `IndexError` traceback | clean `Unhandled string '1-2-3'` (`main-equivalents/c`) |
| 06_empty_items_global.conf | bad `selected_cpus` inherited from `[global]` (`scaling.py:42`) | `IndexError` traceback | clean error, as above |
| 07_empty_stressors_curve.conf | `stressor_range=1-8-2` with `curve` (`benchmarks.py:118`) | validation passes, then `IndexError` while expanding | `curve` does not exist; the empty range itself is pre-existing, see B |
| 09_empty_group_curve.conf | `selected_cpus=0-3 7-4` with `curve` (`scaling.py:63`) | `IndexError` traceback | `curve` does not exist; the empty group itself is pre-existing, see B |
| 12_each_numa_cpuless_node.conf | `each-numa` / `each-quadrant` with a CPU-less NUMA node (`config_helpers.py:26-35`) | helpers give a bogus `['']` group: `TypeError` in `sorted()` with `plus_1`, `ValueError` `int('')` with `iterate` | `numa-simple` did not crash (`main-equivalents/d`) and an explicit `quadrant1` failed cleanly with `Quadrant 1 does not exists` (`main-equivalents/e`). The helpers lost that guard |
| 15_removed_helper_hidden_simple.conf | scaling keyword before `selected_cpus=simple` (`config_syntax.py:111-119`) | generic `didn't get processed ! : ['simple']`; the migration message is never shown | `simple` still worked |
| 16_removed_helper_hidden_numa_simple.conf | same with `numa-simple` | confusing `Non-numeric range ['', ''] in '-'` | `numa-simple` still worked |

The 12 case needs a topology with a CPU-less node (CXL/HBM). It was reproduced with a
mocked `numactl -H` output where node 1 has no cpus and node 2 has cpus 4-7.

## B. Pre-existing on main (for later)

Same result on `main` and on `pr-132-up`, so the PR did not introduce them.

| File | Config | Result on both branches | Root cause | Code on `main` | Code on `pr-132-up` | Fix |
|------|--------|-------------------------|------------|----------------|---------------------|-----|
| 08_empty_stressors_plus1.conf | `stressor_range=1-8-2` (parsed as `[]`), default scaling | no error, 0 benchmarks (`main-equivalents/g`) | `parse_range` silently drops a 3-part range and `validate_stressor_range` accepts anything | `config/config.py:289-293`, `config/config_syntax.py:63-65`, loop at `bench/benchmarks.py:182` | `config/config.py:292-297`, `config/config_syntax.py:67-69`, `bench/scaling.py:56` | issue 2 (on `main`: B1) |
| 10_empty_group_iterate.conf | `selected_cpus=0-3 7-4`, `iterate` | no error; 2nd benchmark has 0 cpus and 0 stressors | a reversed range gives an empty group and `validate_selected_cpus` accepts it | `config/config.py:293`, `config/config_syntax.py:91-92`, stressor count at `bench/benchmarks.py:189` | `config/config.py:296`, `config/config_syntax.py:101-102`, `bench/benchmarks.py:150` | issue 3 (on `main`: B2) |
| 11_empty_group_plus1.conf | same, `plus_1` | no error; both benchmarks pin the same 4 cpus | same | merge at `bench/benchmarks.py:130-136` | merge at `bench/benchmarks.py:103` | issue 3 (on `main`: B2) |
| 13_overlapping_groups_plus2.conf | `selected_cpus=0-3 2-5`, `plus_2` | `pinned_cpu=[0,1,2,2,3,3,4,5]`: 6 distinct cpus, 8 stressors | merged groups are sorted but never de-duplicated | `bench/benchmarks.py:130-136` (append, then `sorted`), count at `:189` | `bench/benchmarks.py:103`, count at `:150` | issue 6 (on `main`: B3) |
| 14_overlapping_numa_quadrant.conf | `numa0 quadrant0`, `plus_1` | step 2 pins 48 cpus of which 32 are distinct, 48 stressors | same | same as 13 | same as 13 | issue 6 (on `main`: B3) |

The "Fix" column refers to "Code locations and suggested fixes" below (written against
`pr-132-up`); B1-B4 are the same fixes as patches against `main`.

Related pre-existing weaknesses seen in group A:
- The root cause of 07 and 09 is the empty list or empty group above (08, 10, 11). The PR
  only adds a new `curve` path that crashes on it.
- On a topology with a CPU-less node, `numa-simple` on `main` skipped the last NUMA node
  and repeated an earlier group (`main-equivalents/d`: 2 benchmarks of 4 cpus, node 2
  never used). The loop over `range(get_numa_domains_count())` assumes node ids without
  gaps: `main` `hwbench/config/config_helpers.py:44-45`, inherited by `each-numa` at
  `pr-132-up` `hwbench/config/config_helpers.py:29` (fix: issue 7 on `pr-132-up`, B4 on `main`), on top of the new
  empty group.

## Code locations and suggested fixes

One entry per distinct issue. Paths and line numbers are those of `pr-132-up`. The fixes
were not applied or tested.

### 1. `plus_<x>` placeholder and `plus_²` accepted (configs 01, 02, 03; introduced)

Code: `hwbench/bench/scaling.py:34-37`. The lookup uses `value` itself when `is_plus` is
False, and `"plus_<x>"` is an entry of `SCALINGS`. `isnumeric()` on line 35 also accepts
`²`, which `int()` rejects.

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

### 2. Empty item list (configs 04, 06, 07; introduced, root cause pre-existing: 08)

Code: `hwbench/bench/scaling.py:42` (`items[0]` on an empty list) and `scaling.py:39-41`.
For a stressor `curve`, `count` ends up in `steps`, which gives `[[]]`, and
`hwbench/bench/benchmarks.py:118` (`stressor_range[step[-1]]`) then fails.
Root cause: `hwbench/config/config.py:292-297`, where `parse_range` silently drops an item
containing `-` that does not split into 2 parts, such as `1-2-3`.

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

### 3. Empty cpu group (configs 09, 10, 11; `curve` crash introduced, acceptance pre-existing)

Code: `hwbench/bench/scaling.py:59-64`, where `items[index][0]` and `items[index + 1][0]` fail
on `[]` (the `IndexError` in 09). The group gets there because
`hwbench/config/config.py:296` builds `range(7, 5)` for a reversed range `7-4`, and
`hwbench/config/config_syntax.py:101-102` only checks that the overall result is
non-empty.

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

### 4. Validation order depends on keyword order (configs 04, 06, 15, 16; introduced)

Code: `hwbench/config/config_syntax.py:111-119` (and the same pattern at `72-77` for
`validate_stressor_range_scaling`). The scaling validator calls
`config.get_selected_cpus()` before `validate_selected_cpus` has checked the value, and
`validate_section` visits keys in file order (`hwbench/config/config.py:250`).

Fix, in `validate_selected_cpus_scaling`:
```python
message = validate_selected_cpus(config, section_name, config.get_section(section_name)["selected_cpus"])
if message:
    return message
```
Alternatively, make `validate_section` validate `selected_cpus` and `stressor_range`
before their `*_scaling` keywords. The stale `simple` in the regex at
`hwbench/config/config.py:208` can go at the same time.

### 5. Empty groups from `each-numa` / `each-quadrant` (config 12; introduced)

Code: `hwbench/config/config_helpers.py:14-16` (`groups()` keeps empty lists, which become a
double space and then the group `['']`), `config_helpers.py:29` and `35` (loops over
`range(count)` of ids). `hwbench/environment/numa.py:21` only records nodes whose line
matches `cpus: ...`, so a CPU-less node leaves a gap in the ids.

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

### 6. Overlapping groups keep duplicate cpus (configs 13, 14; pre-existing)

Code: `hwbench/bench/benchmarks.py:103`. The merge sorts but does not de-duplicate, and
line 150 (`stressor_count = len(pinned_cpu)`) then counts the duplicates.

Fix:
```python
pinned_cpu = sorted({cpu for item in items for cpu in (item if isinstance(item, list) else [item])})
```
Or reject overlapping groups in `validate_selected_cpus_scaling`.

### 7. Skipped NUMA node on id gaps (`main-equivalents/d`; pre-existing)

Same loop as issue 5: `hwbench/config/config_helpers.py:29`. On `main` the equivalent
was the `numa-simple` helper. Fixed by iterating over the real node ids, as above.

## Fixes for the pre-existing issues, as patches against main

The fixes above are written against `pr-132-up`. The pre-existing issues also exist on
`main`, where the code has a different shape, so here are the equivalent fixes there.
Not applied or tested. Each one is scoped to the validation of the keyword concerned,
because `parse_range` is also used for `engine_module_parameter` values, which may
contain dashes.

### B1. Empty `stressor_range` (config 08; `main` `config/config_syntax.py:63-65`)

`validate_stressor_range` accepts anything, and `parse_range` returns `[]` for `1-8-2`.

```python
def validate_stressor_range(config, section_name, value) -> str:
    """Validate the stressor range syntax."""
    if not config.parse_range(value):
        return f"'{value}' is not a valid stressor range (expected x, x-y or x,y,z)"
    return ""
```

### B2. Reversed range gives an empty cpu group (configs 10, 11; `main` `config/config.py:289-293`)

`range(7, 5)` is empty, and `validate_selected_cpus` (`config/config_syntax.py:91-92`)
only checks that the overall result is not empty. A reversed range is never valid, so
reject it where it is parsed:

```python
if len(ranges) == 2:
    if not ranges[0].isnumeric() or not ranges[1].isnumeric():
        h.fatal(f"Non-numeric range {ranges} in '{input}'")
    if int(ranges[0]) > int(ranges[1]):
        h.fatal(f"Reversed range {item!r} in '{input}'")
```

### B3. Overlapping groups keep duplicate cpus (configs 13, 14; `main` `bench/benchmarks.py:130-136`)

The `plus_<x>` branch accumulates cpus with `pinned_cpu.append(cpu)` and passes
`sorted(pinned_cpu.copy())`. Use a set at that call, and in the `none` branch too
(`bench/benchmarks.py:148`), where `sorted(selected_cpus)` keeps duplicates from a flat
`selected_cpus=0-3,2-5`:

```python
self.__schedule_benchmarks(
    job,
    stressor_range_scaling,
    sorted(set(pinned_cpu)),
    validate_parameters,
)
```

### B4. NUMA node skipped on id gaps (`main-equivalents/d`; `main` `config/config_helpers.py:42-47`)

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

`numa_simple` no longer exists on `pr-132-up`; the same loop shape is in `each_numa` and
`each_quadrant` (`config_helpers.py:29`, `:35`), covered by issues 5 and 7 above.

## Controls (not issues)

| File | Purpose |
|------|---------|
| 05_empty_items_selected_first_CONTROL.conf | 04 with the keywords swapped: clean `Unhandled string '1-2-3'` |
| 17_removed_helper_CONTROL.conf | 15 with the keywords swapped: clean `simple was removed, use ...` |

## Review findings without a config

- `cpu_list_to_range` sorting its argument in place (`pr-132-2.json` #2, `pr-132-4.json`
  #1, `pr-132-5.json` #1) and the removed graph code and `pyyaml` dependency
  (`pr-132-2.json` #1, `pr-132-4.json` #2). They come from reviewing `pr-132`, a branch
  behind `main`. Against `pr-132-up`, `hwbench/utils/helpers.py` only gains
  `format_duration` and `graph/` is unchanged, so they do not apply.
- Stale `simple` in the leftover-keyword regex of `get_selected_cpus` (`pr-132-3.json`
  #1): maintainability only, no config changes behaviour because of it.
- `pr-132-6.json` reported no findings.

## main-equivalents/

Old-syntax versions of the configs above, each with a `# Run on main:` header giving the
result on `main`. `d_numa_simple_cpuless.conf` and `e_explicit_quadrant_cpuless.conf` need
the CPU-less topology of file 12.

## Validation of the code links and fixes

Checked against the `pr-132-crashes` branch, whose code is identical to `pr-132-up`
(this branch only adds `crashes/`), and against `main` for the `main` references.

- **Code links:** every `file:line` reference was printed from `git show <branch>:<file>`
  and matches the code it describes.
- **Fixes 1-7 (`pr-132-up`):** applied together in a scratch worktree. The existing
  suite still passes (102 tests, same as before the fixes) and every config in this
  directory then gives a clean error, or a correct result for the ones that should run:
  - 01-03, 15, 16: `unknown value ...` and the `... was removed, use ...` message.
  - 04, 06-11: a clean fatal. The `scaling()` guards (`no items to scale`,
    `empty group of cpus`) also work on their own, without the `parse_range` change.
  - 12: `[[0, 1, 2, 3], [4, 5, 6, 7]]` for both `each-numa` and `each-quadrant`, and the
    job runs.
  - 13, 14: 6 and 32 distinct cpus, with matching stressor counts.
- **Fixes B1-B4 (`main`):** applied in a scratch worktree of `main`. The suite still
  passes (70 tests). 08 and `main-equivalents/g` give the `not a valid stressor range`
  error, 10 and 11 give `Reversed range '7-4'`, 13 and 14 pin 6 and 32 distinct cpus, and
  `main-equivalents/d` now uses node 2 (2 benchmarks of 4 and 8 cpus).
- **Side effect on the controls:** with the `parse_range` change of issue 2, 05 reports
  `Invalid range '1-2-3'` instead of `Unhandled string '1-2-3'`. Without it, 05 keeps its
  original message.
- **Not verified:** that stress-ng treats a stressor count of 0 as one stressor per online
  cpu, since there is no real stress-ng on the host that ran these checks.
