from __future__ import annotations

from dataclasses import dataclass

from graph.auto_traces import ascii_directory_name
from graph.common import fatal
from graph.trace import Trace
from hwbench.bench.monitoring_structs import MonitoringContextKeys, PowerCategories, PowerConsumptionContextKeys
from hwbench.environment.environment_file import location_line, split_location

# The directory of --outdir rendering the groups, as with --same-group
GROUP_DIRECTORY = "by_group"
# The power metrics the graphs of a group add up
GROUP_METRICS = [
    (PowerConsumptionContextKeys.BMC, PowerCategories.SERVER),
    (PowerConsumptionContextKeys.CPU, "package"),
]


@dataclass
class LocationGroup:
    """The traces of the servers sharing a place, from the widest key of their location to this one."""

    location: dict[str, str]
    traces: list[Trace]

    def directories(self) -> list[str]:
        """The subdirectories of by_group/ rendering the group, one per key of its location, from the widest:
        named like the location line, 'Rack A12' giving Rack_A12."""
        names = []
        for key, value in self.location.items():
            name = ascii_directory_name(location_line({key: value}) or "")
            if not name:
                fatal(f"auto-group: the {key} '{value}' has no character usable in a directory name")
            names.append(name)
        return names

    def name(self) -> str:
        return "/".join(self.directories())

    def place_name(self) -> str:
        """The name of the place of the group, its narrowest directory: 'Rack_A12'."""
        return self.directories()[-1]


def location_groups(traces: list[Trace]) -> list[LocationGroup]:
    """The groups of the traces by the wide part of their location, from the widest place to the narrowest.

    Every place of the hierarchy holds the traces located in it or below. A place holding a
    single trace is not a group, nor a place holding the same traces as its single subplace:
    its graphs would be the ones of that subplace.
    """
    places: dict[tuple, list[Trace]] = {}
    for trace in traces:
        wide = list(split_location(trace.get_location())[0].items())
        for depth in range(1, len(wide) + 1):
            places.setdefault(tuple(wide[:depth]), []).append(trace)

    groups = []
    for place, place_traces in places.items():
        subplaces = [other for other in places if len(other) == len(place) + 1 and other[: len(place)] == place]
        if len(place_traces) < 2:
            continue
        if len(subplaces) == 1 and len(places[subplaces[0]]) == len(place_traces):
            continue
        groups.append(LocationGroup(dict(place), place_traces))

    by_name: dict[str, list[LocationGroup]] = {}
    for group in groups:
        by_name.setdefault(group.name(), []).append(group)
    for name, same in by_name.items():
        if len(same) > 1:
            places_found = ", ".join(repr(location_line(group.location)) for group in same)
            fatal(f"auto-group: the places {places_found} are all rendered in the directory {name}")
    return sorted(groups, key=lambda group: group.directories())


def group_problem(group: LocationGroup) -> str | None:
    """Why the graphs of a group cannot be rendered, or None.

    They add up the samples of the same benchmarks of the servers: every trace must have
    the benchmarks of the first one, set the same way, and the power metrics added up.
    """
    reference = group.traces[0]
    for trace in group.traces:
        if sorted(trace.bench_list()) != sorted(reference.bench_list()):
            return f"{trace.get_name()} does not have the benchmarks of {reference.get_name()}"
        for bench_name in sorted(reference.bench_list()):
            difference = reference.bench(bench_name).differences(trace.bench(bench_name))
            if difference:
                return difference.splitlines()[0]
            for context, category in GROUP_METRICS:
                try:
                    trace.bench(bench_name).get_single_metric(MonitoringContextKeys.PowerConsumption, context, category)
                except KeyError:
                    return f"{trace.get_name()} has no '{context}/{category}' metric in {bench_name}"
    return None
