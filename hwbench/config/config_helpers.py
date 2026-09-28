from hwbench.environment import hardware as env_hw

# The selected_cpus helpers: each name is a function of this module, dashes mapped to
# underscores. Listed longest-first so a shorter name cannot partially match a longer one.
HELPERS = ["each-quadrant", "each-core", "each-numa"]

# Removed helpers, rejected with the way to write the same selection
REMOVED_HELPERS = {
    "numa-simple": "selected_cpus=each-numa with selected_cpus_scaling=plus_1",
    "simple": "selected_cpus=each-core with selected_cpus_scaling=curve",
}


def groups(cpu_lists: list[list[int]]) -> str:
    """Return cpu lists as selected_cpus groups, one group per list."""
    return " ".join(",".join(str(cpu) for cpu in sorted(cpus)) for cpus in cpu_lists)


def each_core(hardware: env_hw.BaseHardware) -> str:
    """Return one group per physical core, with all its logical cores."""
    return groups(
        [cores for physical_cores in hardware.get_cpu().get_cores_by_socket().values() for cores in physical_cores]
    )


def each_numa(hardware: env_hw.BaseHardware) -> str:
    """Return one group per NUMA domain."""
    cpu = hardware.get_cpu()
    return groups([cpu.get_logical_cores_in_numa_domain(domain) for domain in range(cpu.get_numa_domains_count())])


def each_quadrant(hardware: env_hw.BaseHardware) -> str:
    """Return one group per quadrant."""
    cpu = hardware.get_cpu()
    return groups([cpu.get_cores_in_quadrant(quadrant) for quadrant in range(cpu.get_quadrants_count())])
