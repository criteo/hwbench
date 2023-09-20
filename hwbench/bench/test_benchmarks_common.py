import pathlib
from ..environment.cpu import MockCPU
from ..environment.cpu_info import CPU_INFO
from ..environment.cpu_cores import CPU_CORES
from ..environment.numa import NUMA
from ..environment.mock import MockHardware


def load_mocked_hardware(
    cpuinfo=None,
    cpucores=None,
    numa=None,
):
    def load(target, path):
        instance = target(path)
        stdout = (path / "stdout").read_bytes()
        stderr = (path / "stderr").read_bytes()
        instance.parse_cmd(stdout, stderr)
        return instance

    fake_numa = None
    if numa:
        fake_numa = load(NUMA, pathlib.Path(numa))

    fake_cpuinfo = None
    if cpuinfo:
        fake_cpuinfo = load(CPU_INFO, pathlib.Path(cpuinfo))

    fake_cpucores = None
    if cpucores:
        fake_cpucores = load(CPU_CORES, pathlib.Path(cpucores))

    cpu = MockCPU(".", fake_cpuinfo, fake_cpucores, fake_numa)
    return MockHardware(cpu=cpu)
