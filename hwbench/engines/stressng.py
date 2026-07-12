from __future__ import annotations

import pathlib
import re

import yaml

from hwbench.bench.benchmark import ExternalBench
from hwbench.bench.engine import EngineBase, EngineModuleBase
from hwbench.bench.parameters import BenchmarkParameters
from hwbench.utils import helpers as h


class EngineModulePinnable(EngineModuleBase):
    def validate_module_parameters(self, params: BenchmarkParameters):
        pinned = params.get_pinned_cpu()
        if pinned == "":
            return ""
        if not isinstance(pinned, list):
            pinned = [pinned]
        for cpu in pinned:
            if params.get_hw().logical_core_count() <= int(cpu):
                return f"Cannot pin on core #{cpu} we only have {params.get_hw().logical_core_count()} cores"
        return ""


class Engine(EngineBase):
    """The main stressn2 class."""

    def __init__(self):
        from .stressng_cpu import EngineModuleCpu
        from .stressng_memrate import EngineModuleMemrate
        from .stressng_qsort import EngineModuleQsort
        from .stressng_stream import EngineModuleStream
        from .stressng_vnni import EngineModuleVNNI

        super().__init__("stressng", "stress-ng")
        self.add_module(EngineModuleCpu(self, "cpu"))
        self.add_module(EngineModuleQsort(self, "qsort"))
        self.add_module(EngineModuleStream(self, "stream"))
        self.add_module(EngineModuleMemrate(self, "memrate"))
        self.add_module(EngineModuleVNNI(self, "vnni"))
        self.version = ""

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = stdout.split()[2].decode()
        return self.version

    def get_version(self) -> str:
        return self.version

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class StressNG(ExternalBench):
    """The StressNG base class for stressors."""

    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        ExternalBench.__init__(self, engine_module, parameters)
        self.stressor_name = parameters.get_engine_module_parameter()
        self.engine_module = engine_module
        self.parameters = parameters

    def version_compatible(self) -> bool:
        engine = self.engine_module.get_engine().get_version()
        return h.versiontuple(engine) >= h.versiontuple("0.17.4")

    def need_skip_because_version(self):
        if self.skip:
            # we already skipped this benchmark, we can't know the reason anymore
            # because we might not have run the version command.
            return ["echo", "skipped benchmark"]
        if not self.version_compatible():
            print(f"WARNING: skipping benchmark {self.name}, needs stress-ng >= 0.17.04")
            self.skip = True
            return ["echo", "skipped benchmark"]
        return None

    def run_cmd(self) -> list[str]:
        skip = self.need_skip_because_version()
        if skip:
            return skip

        # Let's build the command line to run the tool
        args = [
            self.engine_module.get_engine().get_binary(),
            "--timeout",
            str(self.parameters.get_runtime()),
            "--metrics",
            "--yaml",
            f"{self.output_basename}.yaml",
        ]

        return self.get_taskset(args)

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name() + self.stressor_name

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def stats_parse(self) -> re.Pattern:
        """Return a regexp pattern to match the stats metrics"""
        # stress-ng: metrc: [58878] stressor       bogo ops real time  usr time  sys time   bogo ops/s     bogo ops/s CPU used per       RSS Max
        # stress-ng: metrc: [58878]                           (secs)    (secs)    (secs)   (real time) (usr+sys time) instance (%)          (KB)
        # stress-ng: metrc: [58878] stream            39999     10.01   1231.71     48.89      3995.57          31.23        99.94         14360

        return re.compile(
            r"stress-ng: metrc:"
            r"\s+\[(?P<pid>[0-9]+)\] "
            r"(?P<engine>[a-z]+)"
            r"\s+(?P<bogo_ops>[0-9]+)"
            r"\s+(?P<real_time>[0-9\.]+)"
            r"\s+(?P<user_time>[0-9\.]+)"
            r"\s+(?P<sys_time>[0-9\.]+)"
            r"\s+(?P<bogo_ops_sec>[0-9\.]+)"
            r"\s+(?P<bogo_ops_sec_realtime>[0-9\.]+)"
            r"\s+(?P<cpu_used_percent>[0-9\.]+)"
            r"\s+(?P<rss_max>[0-9\.]+)"
        )

    def yaml_output_file(self) -> pathlib.Path:
        """Path of the YAML metrics file emitted by stress-ng (see run_cmd)."""
        return self.out_dir / f"{self.output_basename}.yaml"

    def parse_yaml_per_instance(self) -> dict:
        """Extract the per-instance bogo-ops from the stress-ng YAML output.

        stress-ng reports, under each stressor of the "metrics:" section, an
        "instances:" list holding a per-second bogo-ops rate per instance:

            metrics:
                - stressor: cpu
                  bogo-ops: 3257280
                  ...
                  instances:
                      - instance: 0
                        bogo-ops: 5120
                        bogo-ops-per-second-real-time: 341.098366
                        ...

        We keep the per-instance metric so it can be inspected/plotted later.
        The YAML file is optional (older stress-ng, or a skipped run); when it
        is missing we simply return an empty dict and change nothing.
        """
        yaml_file = self.yaml_output_file()
        if not yaml_file.exists():
            return {}

        with yaml_file.open() as f:
            data = yaml.safe_load(f)

        bogo_ops: list[float] = []
        for stressor in (data or {}).get("metrics", []):
            for instance in stressor.get("instances", []):
                if "bogo-ops-per-second-real-time" in instance:
                    bogo_ops.append(float(instance["bogo-ops-per-second-real-time"]))

        if not bogo_ops:
            return {}

        return {"detail": {"bogo op/s": bogo_ops}}

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        """Generic stress-ng output parsing to extract performance metrics."""
        for line in (stdout or stderr).splitlines():
            stats = self.stats_parse().search(str(line))
            if stats:
                s = stats.groupdict()
                return (
                    self.parameters.get_result_format()
                    | {
                        "bogo ops/s": float(s["bogo_ops_sec"]),
                        "effective_runtime": float(s["real_time"]),
                    }
                    | self.parse_yaml_per_instance()
                )

        h.fatal("Unable to detect stress-ng reporting metrics")

    def empty_result(self):
        """Default empty results for stress-ng"""
        return {
            "bogo ops/s": 0,
            "effective_runtime": 0,
            "skipped": True,
        }
