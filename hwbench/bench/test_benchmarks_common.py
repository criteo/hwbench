import ast
import dataclasses
import pathlib
import unittest
from functools import reduce
from unittest.mock import patch

import pytest

from hwbench.bench.monitoring_structs import MonitoringContextKeys
from hwbench.config import config
from hwbench.environment.cpu import MockCPU
from hwbench.environment.cpu_cores import CPU_CORES
from hwbench.environment.cpu_info import CPU_INFO
from hwbench.environment.mock import MockHardware
from hwbench.environment.numa import NUMA

from . import benchmarks


class TestCommon(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def load_mocked_hardware(
        self,
        cpuinfo=None,
        cpucores=None,
        numa=None,
    ):
        """Create a fake hardware context"""

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
        self.hw = MockHardware(cpu=cpu)

    def load_benches(self, jobs_config_file: str):
        """Turn jobs_config_file into benchmarks"""
        self.jobs_config = config.Config(jobs_config_file)
        self.jobs_config.set_hardware(self.hw)
        self.benches = benchmarks.Benchmarks(".", self.jobs_config)
        self.benches.set_hardware(self.hw)

    def get_bench_parameters(self, index):
        """Return the benchmark parameters."""
        return self.benches.get_benchmarks()[index].get_parameters()

    def get_benches(self):
        return self.benches

    def parse_jobs_config(self, validate_parameters=True, gpus=None):
        # We need to mock turbostat when parsing config with monitoring
        # We mock the run() and check_version() command to get a constant output
        # The GPUs of the machine running the tests are hidden too, so the
        # monitoring metrics do not depend on the test host.
        with patch("hwbench.environment.turbostat.Turbostat.check_version") as cv:
            cv.return_value = True
            with (
                patch("hwbench.environment.turbostat.Turbostat.run") as ts,
                patch("hwbench.bench.monitoring.list_gpus", return_value=gpus or {}),
                patch("hwbench.environment.hardware.list_gpus", return_value=gpus or {}),
                open("hwbench/tests/parsing/turbostat/run") as f,
            ):
                ts.return_value = ast.literal_eval(f.read())
                return self.benches.parse_jobs_config(validate_parameters)

    def monitoring_members(self, monitoring, metric: MonitoringContextKeys) -> int:
        """Return the number of components a monitoring context holds."""
        if monitoring is None:
            return 0
        data = dataclasses.asdict(monitoring.metrics.contexts)[str(metric)]
        return reduce(lambda acc, family: acc + len(family), data.values(), 0)

    def get_jobs_config(self) -> config.Config:
        return self.jobs_config

    def bench_name(self, index) -> str:
        """Return the benchmark name"""
        return self.get_bench_parameters(index).get_name()

    def gpu_list(self, index) -> list[int]:
        """Return the GPUs a benchmark was given."""
        return self.get_bench_parameters(index).get_pinned_gpus()

    def bench_em(self, index) -> str:
        """Return the benchmark engine module name"""
        return self.benches.get_benchmarks()[index].get_enginemodule().get_name()

    def bench_emp(self, index) -> str:
        """Return the benchmark engine module parameter"""
        return self.get_bench_parameters(index).get_engine_module_parameter()

    def should_be_fatal(self, func, *args):
        """Test if the function func is exiting."""
        with pytest.raises(SystemExit):
            func(*args)

    def assert_job(self, index, name, engine_module, engine_module_parameter=None):
        """Assert if a benchmark does not match the jobs_config file description."""
        # If not engine_module_parameter set, let's consider the engine_module
        if not engine_module_parameter:
            engine_module_parameter = engine_module
        assert self.bench_name(index) == name
        assert self.bench_em(index) == engine_module
        assert self.bench_emp(index) == engine_module_parameter


def fake_gpus(count: int) -> dict[str, dict]:
    """Return the inventory of a fake <count> accelerators host."""
    return {
        str(index): {
            "index": index,
            "uuid": f"GPU-fake-{index}",
            "name": "Fake GPU",
            "device_type": "GPU",
            "memory_total_mb": 81559,
            "detail": {},
        }
        for index in range(count)
    }
