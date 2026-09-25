"""The scaling shared by selected_cpus_scaling and stressor_range_scaling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hwbench.environment.cpu import CPU

# The values each keyword accepts: plus_<x> stands for plus_1, plus_2...
SCALINGS = {
    "selected_cpus_scaling": ["iterate", "none", "plus_<x>", "curve"],
    "stressor_range_scaling": ["plus_<x>", "curve"],
}


def scaling(keyword: str, value: str, items: list[Any], cpu: CPU | None = None) -> list[list[int]]:
    """Return, for each step of a scaling, the indexes of the items it takes.

    The items are the groups of selected_cpus, or the counts of stressor_range, in the
    order they are written. A CPU step merges its groups, a stressor step runs the count of
    its last index.
    - iterate: one item per step
    - none: all the items in a single step
    - plus_<x>: the first x items, then the first 2x items... the item count must be a
      multiple of x
    - curve: the first 1, 2, 3, 4, 8, 16 then +16 items, and all of them; with the cpu, the
      last group of each socket too, so a full socket is measured before the next one

    A single item gives a single step, whatever the value. Raises ValueError with the
    message to report when the value is unknown for this keyword, or impossible for these
    items: the validators and the expansion both rely on this single function.
    """
    increment = value.replace("plus_", "", 1)
    is_plus = value.startswith("plus_") and increment.isnumeric() and int(increment) > 0
    if ("plus_<x>" if is_plus else value) not in SCALINGS[keyword]:
        raise ValueError(f"unknown value {value}")

    count = len(items)
    if count == 1:
        return [[0]]
    groups = keyword == "selected_cpus_scaling" and isinstance(items[0], list)
    if value == "iterate":
        return [[index] for index in range(count)]
    if value == "none":
        if groups:
            raise ValueError("none needs a single group of cpus, got several")
        return [list(range(count))]
    if keyword == "selected_cpus_scaling" and not groups:
        raise ValueError(f"{value} needs groups to accumulate, like selected_cpus=each-core")

    if is_plus:
        # An item count that is not a multiple would lead to an unbalanced last step
        if count % int(increment) != 0:
            raise ValueError(f"{value} needs a multiple of {increment} items, got {count}")
        steps = set(range(int(increment), count + 1, int(increment)))
    else:
        steps = {1, 2, 3, 4, 8, 16, count} | set(range(32, count + 1, 16))
        if groups and cpu:
            steps |= {
                index + 1
                for index in range(count - 1)
                if cpu.get_socket(items[index][0]) != cpu.get_socket(items[index + 1][0])
            }
    return [list(range(step)) for step in sorted(steps) if step <= count]
