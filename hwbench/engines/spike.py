import os
import re
import subprocess
import time
from statistics import mean
from ..bench.parameters import BenchmarkParameters
from ..bench.engine import EngineBase, EngineModuleBase
from ..bench.benchmark import ExternalBench
from ..bench import monitoring_structs
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

    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        ExternalBench.__init__(self, engine_module, parameters)
        self.parameters = parameters
        self.engine_module = engine_module
        self.high = 0
        self.low = 0
        self.cycle = 0
        self.auto = False
        # By default, the auto mode will wait fans to speedup by 5% to stop the load
        self.auto_fan_ratio = 5
        self.parse_parameters()

    def parse_parameters(self):
        runtime = self.parameters.runtime
        for param in self.parameters.get_engine_module_parameter_base().split():
            ressources = re.findall(r"\b(high|low):([0-9]+)\b", param)
            if ressources:
                self.auto = False
                for ressource, value in ressources:
                    if ressource == "high":
                        self.high = int(value)
                    else:
                        self.low = int(value)
            if "auto" in param:
                self.auto = True
                match = re.search(r"auto:(?P<fan_ratio>[0-9]+)", param)
                if match:
                    self.auto_fan_ratio = int(match.group("fan_ratio"))

                if self.auto_fan_ratio <= 1:
                    h.fatal("fan_ratio should be greater than 1%")

        if not self.auto:
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

    def get_monotonic_clock(self):
        """Return the raw clock time, not sensible of ntp adjustments."""
        return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)

    def get_fans_speed(self):
        raw_fans = (
            self.parameters.get_monitoring().vendor.get_bmc().read_fans().get(str(monitoring_structs.FanContext.FAN))
        )
        return sum([fan.get_values()[-1] for _, fan in raw_fans.items()])

    def __spawn_stressor(self, additional_args=[], wait_stressor=False):
        args = [
            self.engine_module.engine.get_binary(),
            "-c",
            f"{str(self.parameters.get_engine_instances_count())}",
            "--cpu-method",
            "matrixprod",
        ] + additional_args
        args = self.get_taskset(args)

        if wait_stressor:
            english_env = os.environ.copy()
            english_env["LC_ALL"] = "C"
            return subprocess.run(
                args,
                capture_output=True,
                env=english_env,
                stdin=subprocess.DEVNULL,
            )
        else:
            return subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )

    def auto_spike(self):
        """Perform automatic spiking"""

        def since_start():
            return self.get_monotonic_clock() - start_time

        # 1 cycle is made of <high> seconds loaded + <low> seconds idle
        start_time = self.get_monotonic_clock()
        super().pre_run()

        # Calibrating low_fan_speed
        # The low fan speed may vary a bit between the first read and the real low.
        # This code is making a short calibration over 10 seconds to detect the real low value even if the fans aren't perfectly stable.
        calibration_fans = []
        auto_cycle = 11
        calibration_duration = 3 * auto_cycle
        print(f"[{self.parameters.get_name()}: calibrating fans for {calibration_duration}s to detect low speed")
        for _ in range(0, calibration_duration):
            calibration_fans.append(self.get_fans_speed())
            time.sleep(1)
        # We keep an average value we saw during that period
        initial_low_fans_speed = mean(calibration_fans)

        fans_speed = initial_low_fans_speed
        fans_speed_high = initial_low_fans_speed * (100 + self.auto_fan_ratio) / 100
        wait_high_fans_speed = True
        time_to_reach_high = []
        time_to_reach_low = []
        stressor = None
        cycle_start = self.get_monotonic_clock()
        loops = 0
        while True:
            loops += 1
            current_fan_ratio = (fans_speed / initial_low_fans_speed) * 100
            if loops % 1 == 0:
                print(
                    f"initial:{initial_low_fans_speed} current:{fans_speed} percent:{current_fan_ratio:.2f} high_ratio:{self.auto_fan_ratio} high_fan:{fans_speed_high}"
                )
            if wait_high_fans_speed:
                if not stressor:
                    print("High: Spawing stressor")
                    stressor = self.__spawn_stressor()
                elif fans_speed >= fans_speed_high:
                    # Fans reach the expected speed, let's stop the stress
                    time_to_reach_high.append(self.get_monotonic_clock() - cycle_start)
                    wait_high_fans_speed = False
                    stressor.kill()
                    stressor = None
                    print(f"High: reached {current_fan_ratio:.2f}% with fans={fans_speed}")
                    # Let's reset the cycle start for the low_fan_speed
                    cycle_start = self.get_monotonic_clock()
            else:
                # We are in a descent phase
                if fans_speed < (initial_low_fans_speed * 1.01):
                    # We reached the initial fan speed ~1%, we can prepare the next load cycle
                    time_to_reach_low.append(self.get_monotonic_clock() - cycle_start)
                    print(f"Low: reached {current_fan_ratio:.2f}% with fans={fans_speed}")
                    wait_high_fans_speed = True

            # Time-keeper:
            # Test should not run longer than expected runtime
            # If the next cycle puts us out of the bondaries, let's stop here
            # We let a gentle 2 seconds bonus from the time rounding.
            if since_start() + auto_cycle > self.parameters.get_runtime() + 2:
                if stressor:
                    stressor.kill()
                # Compute the results and return them
                return super().post_run(
                    self.parameters.get_result_format()
                    | {
                        "time_to_high": time_to_reach_high,
                        "time_to_low": time_to_reach_low,
                    }
                )

            # Let's wait the next cycle
            time.sleep(auto_cycle)

            # collect the fans speed for the next iteration
            fans_speed = self.get_fans_speed()

    def manual_spike(self):
        """Perform a manual spiking"""

        def since_start():
            return self.get_monotonic_clock() - start_time

        # 1 cycle is made of <high> seconds loaded + <low> seconds idle
        start_time = self.get_monotonic_clock()

        super().pre_run()

        while True:
            # Let's load the system from <high> seconds on the listed cores
            self.__spawn_stressor(["-t", f"{self.high}"], wait_stressor=True)

            # Let's the system unload for <low> seconds
            time.sleep(self.low)

            # Test should not run longer than expected runtime
            # If the next cycle puts us out of the bondaries, let's stop here
            # We let a gentle 2 seconds bonus from the time rounding.
            if since_start() + self.cycle > self.parameters.get_runtime() + 2:
                return super().post_run(
                    self.parameters.get_result_format()
                    | {
                        "time_to_high": self.high,
                        "time_to_low": self.low,
                    }
                )

            # If we have enough time, let's do another cycle

    def run(self):
        """Do the spike test."""
        if self.cycle:
            return self.manual_spike()
        elif self.auto:
            return self.auto_spike()

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)
