from hwbench.environment import hardware as env_hw

# The selected_cpus helpers: each name is a function of this module, dashes mapped to
# underscores. Listed longest-first so a shorter name (simple) cannot partially match
# a longer one (numa-simple).
HELPERS = ["numa-simple", "each-quadrant", "each-core", "each-numa", "simple"]


def groups(cpu_lists: list[list[int]]) -> str:
    """Return cpu lists as selected_cpus groups, one group per list."""
    return " ".join(",".join(str(cpu) for cpu in sorted(cpus)) for cpus in cpu_lists)


def simple(hardware: env_hw.BaseHardware) -> str:
    """A naive cpu scaling."""
    # 1, 2, 3, 4, 8, 16 then +16 up to the core count
    # 1, 2, 3, 4, 8, 16, 32, 48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 240, 256
    core_count = []
    for test in range(1, 22):
        if test <= 4:
            core_count.append(test)
        elif test <= 6:
            core_count.append((test - 4) * 8)
        else:
            core_count.append((test - 5) * 16)

    # If the number of cores is not modulo 16, the last test is not testing all cores
    # So if we don't have a test with the current max number of cores, let's add it
    if hardware.get_cpu().get_physical_cores_count() not in core_count:
        core_count.append(hardware.get_cpu().get_physical_cores_count())

    # In case of multiple sockets, let's ensure we test a full socket during the scaling
    cores_per_socket = int(hardware.get_cpu().get_physical_cores_count() / hardware.get_cpu().get_sockets_count())
    if cores_per_socket not in core_count:
        core_count.append(cores_per_socket)

    core_count = sorted(core_count)

    global_cpu_list = ""
    for cpus in core_count:
        if cpus <= hardware.get_cpu().get_physical_cores_count():
            cpu_list = []
            for cpu in range(0, cpus):
                cpu_list += hardware.get_cpu().get_peer_siblings(cpu)
            global_cpu_list += ",".join(str(e) for e in sorted(cpu_list)) + " "
    return global_cpu_list.strip()


def numa_simple(hardware: env_hw.BaseHardware) -> str:
    """Return cumulative cpu groups, adding one more NUMA node at each step."""
    cpu = hardware.get_cpu()
    groups = []
    cores: list[int] = []
    for numa_domain in range(cpu.get_numa_domains_count()):
        cores += cpu.get_logical_cores_in_numa_domain(numa_domain)
        groups.append(",".join(str(core) for core in sorted(cores)))
    return " ".join(groups)


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
