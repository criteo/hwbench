import os
import re
import subprocess
import time
from ..bench.parameters import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..bench.benchmark import ExternalBench
from ..utils import helpers as h


class EngineModuleCPUSpike(EngineModuleBase):
    """This class implements the EngineModuleBase for Spike"""

    def __init__(self, engine: EngineBase, engine_module_name: str, fake_stdout=None):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter(fake_stdout)

    def load_module_parameter(self, fake_stdout=None):
        # if needed add module parameters to your module
        self.add_module_parameter("cpu")

    def validate_module_parameters(self, p: BenchmarkParameters):
        msg = super().validate_module_parameters(p)
        Spike(self, p).parse_parameters()
        return msg

    def run_cmd(self, p: BenchmarkParameters):
        return Spike(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return Spike(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return Spike(self, p).fully_skipped_job()


class Engine(EngineBase):
    """The main spike class."""

    def __init__(self, fake_stdout=None):
        super().__init__("spike", "stress-ng")
        self.add_module(EngineModuleCPUSpike(self, "cpu", fake_stdout))

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    def version_major(self) -> int:
        if self.version:
            return int(self.version.split(b".")[1])
        return 0

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class Spike(ExternalBench):
    """The Spike stressor."""

    def __init__(
        self, engine_module: EngineModuleBase, parameters: BenchmarkParameters
    ):
        ExternalBench.__init__(self, engine_module, parameters)
        self.parameters = parameters
        self.engine_module = engine_module
        self.high = 0
        self.low = 0
        self.cycle = 0
        self.parse_parameters()

    def parse_parameters(self):
        runtime = self.parameters.runtime
        for param in self.parameters.get_engine_module_parameter_base().split():
            ressources = re.findall(r"\b(high|low):([0-9]+)\b", param)
            if not ressources:
                h.fatal("Missing high or low keywords in configuration file")
            for ressource, value in ressources:
                if ressource == "high":
                    self.high = int(value)
                else:
                    self.low = int(value)

        # 1 cycle is made of <high> seconds loaded + <low> seconds idle
        self.cycle = self.low + self.high
        if self.cycle == 0:
            h.fatal("No cycle detected, check low and high values")

        if runtime % self.cycle > 0:
            h.fatal(f"Cycles ({self.cycle}s) are not modulo the runtime ({runtime}s)")

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        args = [
            self.engine_module.get_engine().get_binary(),
            str(self.parameters.get_runtime()),
        ]

        return self.get_taskset(args)

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        # There is no score here. Let's report the runtime.
        return self.parameters.get_result_format()

    def run(self):
        """Do the spike test."""

        def get_monotonic_clock():
            """Return the raw clock time, not sensible of ntp adjustments."""
            return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)

        def since_start():
            return get_monotonic_clock() - start_time

        # 1 cycle is made of <high> seconds loaded + <low> seconds idle
        start_time = get_monotonic_clock()

        super().pre_run()

        while True:
            # Let's load the system from <high> seconds on the listed cores
            english_env = os.environ.copy()
            english_env["LC_ALL"] = "C"
            args = [
                self.engine_module.engine.get_binary(),
                "-c",
                f"{str(self.parameters.get_engine_instances_count())}",
                "--cpu-method",
                "matrixprod",
                "-t",
                f"{self.high}",
            ]
            args = self.get_taskset(args)
            subprocess.run(
                args,
                capture_output=True,
                env=english_env,
                stdin=subprocess.DEVNULL,
            )

            # Let's the system unload for <low> seconds
            time.sleep(self.low)

            # Test should not run longer than expected runtime
            # If the next cycle puts us out of the bondaries, let's stop here
            # We let a gentle 2 seconds bonus from the time rounding.
            if since_start() + self.cycle > self.parameters.get_runtime() + 2:
                return super().post_run(self.parameters.get_result_format())

            # If we have enough time, let's do another cycle

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)
