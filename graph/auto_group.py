from __future__ import annotations

from dataclasses import dataclass

from graph.auto_traces import ascii_directory_name
from graph.common import fatal
from graph.trace import Trace
from hwbench.bench.monitoring_structs import (
    CPU_RAM,
    MonitoringContextKeys,
    MonitorMetric,
    PowerCategories,
    PowerConsumptionContextKeys,
)
from hwbench.environment import cooling
from hwbench.environment.environment_file import Location

# The directory of --outdir rendering the groups, as with --same-group
GROUP_DIRECTORY = "by_group"
# The power metric the graphs of a group add up, split by the cooling of the components, see liquid_cooled()
GROUP_METRICS = [
    (PowerConsumptionContextKeys.BMC, PowerCategories.SERVER),
]

# The power metrics of each component of the cooling of the topology, see hwbench/environment/cooling.py:
# the first one a benchmark has, the GPUs being all the ones of the GPU context
LIQUID_COOLED_METRICS: dict[str, list[tuple[str, str]]] = {
    "cpu": [(str(PowerConsumptionContextKeys.CPU), "package")],
    "memory": [
        (str(PowerConsumptionContextKeys.CPU), CPU_RAM),
        (str(PowerConsumptionContextKeys.BMC), str(PowerCategories.MEMORY)),
    ],
}


def liquid_cooled(bench, components: dict[str, str]) -> tuple[dict[str, list[MonitorMetric]], list[str]]:
    """The power metrics of the <components> of a server cooled by a liquid, by the name of the metric, like
    'CPU.package' or 'GPU', and the metrics missing in <bench> for the others, like 'CPU/package'."""
    metrics: dict[str, list[MonitorMetric]] = {}
    missing = []
    power = bench.get_monitoring_metric(MonitoringContextKeys.PowerConsumption)
    for component in cooling.COMPONENTS:
        if components.get(component) != "liquid":
            continue
        if component == "gpu":
            gpus = list(power.get(str(PowerConsumptionContextKeys.GPU), {}).values())
            if gpus:
                metrics[str(PowerConsumptionContextKeys.GPU)] = gpus
            else:
                missing.append(str(PowerConsumptionContextKeys.GPU))
            continue
        found = [
            (context, category)
            for context, category in LIQUID_COOLED_METRICS[component]
            if category in power.get(context, {})
        ]
        if found:
            context, category = found[0]
            metrics[f"{context}.{category}"] = [power[context][category]]
        else:
            missing.append(
                " or ".join(f"{context}/{category}" for context, category in LIQUID_COOLED_METRICS[component])
            )
    return metrics, missing


@dataclass
class LocationGroup:
    """The traces of the servers sharing a place: the start of the path of their location, up to this place."""

    location: Location
    traces: list[Trace]

    def directories(self) -> list[str]:
        """The subdirectories of by_group/ rendering the group, one per known place of its location,
        from the widest: named after the place shown with its level, 'Room 1' giving Room_1."""
        names = []
        for place in self.location.places():
            name = ascii_directory_name(place)
            if not name:
                fatal(f"auto-group: the place '{place}' has no character usable in a directory name")
            names.append(name)
        return names

    def name(self) -> str:
        return "/".join(self.directories())

    def place_name(self) -> str:
        """The name of the place of the group, its narrowest directory: 'Rack_A12'."""
        return self.directories()[-1]


def location_groups(traces: list[Trace]) -> list[LocationGroup]:
    """The groups of the traces by the path of their location, from the widest place to the narrowest.

    Every known place of a path holds the traces whose path starts the same way up to it. A place
    holding a single trace is not a group, nor a place holding the same traces as its single
    subplace: its graphs would be the ones of that subplace.
    """
    places: dict[tuple[str, ...], list[Trace]] = {}
    locations: dict[tuple[str, ...], Location] = {}
    for trace in traces:
        location = trace.get_location()
        if location is None:
            continue
        for depth in range(1, len(location.path) + 1):
            place = tuple(location.path[:depth])
            places.setdefault(place, []).append(trace)
            levels = location.levels[:depth] if location.levels else None
            known = locations.setdefault(place, Location(list(place), location.separator, levels))
            # The levels name the place only when all its servers name it the same way
            if known.levels != levels:
                known.levels = None

    groups = []
    for place, place_traces in places.items():
        # A place not known is not a place to group the servers in, only a step to the next known one
        if not place[-1] or len(place_traces) < 2:
            continue
        subplaces = [
            other
            for other in places
            if len(other) > len(place)
            and other[: len(place)] == place
            and other[-1]
            and not any(other[len(place) : -1])
        ]
        if len(subplaces) == 1 and len(places[subplaces[0]]) == len(place_traces):
            continue
        groups.append(LocationGroup(locations[place], place_traces))

    by_name: dict[str, list[LocationGroup]] = {}
    for group in groups:
        by_name.setdefault(group.name(), []).append(group)
    for name, same in by_name.items():
        if len(same) > 1:
            places_found = ", ".join(repr(group.location.line()) for group in same)
            fatal(f"auto-group: the places {places_found} are all rendered in the directory {name}")
    return sorted(groups, key=lambda group: group.directories())


def group_benches(group: LocationGroup, skipped: bool = True) -> list[str]:
    """The benchmarks every server of a group has: the job file expands differently from a machine to another.
    Without <skipped>, only the ones every server ran: not a job a server skipped, like an AVX-512 one on a
    CPU without it, that has no monitoring."""
    names = set.intersection(*(set(trace.bench_list()) for trace in group.traces))
    if not skipped:
        names = {name for name in names if not any(trace.bench_list()[name].get("skipped") for trace in group.traces)}
    return sorted(names)


def group_problem(group: LocationGroup) -> str | None:
    """Why the graphs of a group cannot be rendered, or None.

    They add up the samples of the benchmarks every server ran: the servers must have run the
    job file of the first one, as the scaling requires, and report the power metrics added up.
    Its benchmarks may be set differently from a machine to another, like the workers of
    stressor_range=auto.
    """
    reference = group.traces[0]
    for trace in group.traces:
        if trace.get_original_config() != reference.get_original_config():
            return f"{trace.get_name()} does not have the job file of {reference.get_name()}"
    benches = group_benches(group, skipped=False)
    if not benches:
        return "no benchmark ran by every server"
    for trace in group.traces:
        for bench_name in benches:
            for context, category in GROUP_METRICS:
                try:
                    trace.bench(bench_name).get_single_metric(MonitoringContextKeys.PowerConsumption, context, category)
                except KeyError:
                    return f"{trace.get_name()} has no '{context}/{category}' metric in {bench_name}"
            _, missing = liquid_cooled(trace.bench(bench_name), trace.get_cooling())
            if missing:
                return (
                    f"{trace.get_name()} has no '{missing[0]}' metric in {bench_name}, "
                    "the power of a component cooled by a liquid"
                )
    return None
