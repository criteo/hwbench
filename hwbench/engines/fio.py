import json
import pathlib
from typing import Any

from hwbench.bench.benchmark import ExternalBench
from hwbench.bench.engine import EngineBase, EngineModuleBase
from hwbench.bench.parameters import BenchmarkParameters
from hwbench.utils.helpers import fatal, versiontuple


class EngineModuleCmdline(EngineModuleBase):
    """This class implements the EngineModuleBase for fio"""

    def __init__(self, engine: EngineBase, engine_module_name: str, fake_stdout=None):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter(fake_stdout)

    def load_module_parameter(self, fake_stdout=None):
        # if needed add module parameters to your module
        self.add_module_parameter("cmdline")

    def validate_module_parameters(self, p: BenchmarkParameters):
        msg = super().validate_module_parameters(p)
        FioCmdLine(self, p).parse_parameters()
        return msg

    def run_cmd(self, p: BenchmarkParameters):
        return FioCmdLine(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return FioCmdLine(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return FioCmdLine(self, p).fully_skipped_job()


class Engine(EngineBase):
    """The main fio class."""

    def __init__(self, fake_stdout=None):
        super().__init__("fio", "fio")
        self.add_module(EngineModuleCmdline(self, "cmdline", fake_stdout))

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = stdout.split(b"-")[1].strip().decode()
        return self.version

    def get_version(self):
        return self.version

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class Fio(ExternalBench):
    """The Fio stressor."""

    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        ExternalBench.__init__(self, engine_module, parameters)
        self.parameters = parameters
        self.engine_module = engine_module
        self.log_avg_msec = 20000  # write_*_log are averaged at 20sec
        self._parse_parameters()
        # Tests can skip this part
        if isinstance(parameters.out_dir, pathlib.PosixPath):
            parameters.out_dir.joinpath("fio").mkdir(parents=True, exist_ok=True)

    def version_compatible(self) -> bool:
        engine = self.engine_module.get_engine()
        return versiontuple(engine.get_version()) >= versiontuple("3.19")

    def _parse_parameters(self):
        self.runtime = self.parameters.runtime
        if self.runtime * 1000 < self.log_avg_msec:
            fatal(f"Fio runtime cannot be lower than the average log time ({self.log_avg_msec}).")

    def need_skip_because_version(self):
        if self.skip:
            # we already skipped this benchmark, we can't know the reason anymore
            # because we might not have run the version command.
            return ["echo", "skipped benchmark"]
        if not self.version_compatible():
            print(f"WARNING: skipping benchmark {self.name}, needs fio >= 3.19")
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
        ]

        return self.get_taskset(args)

    def get_default_fio_command_line(self, args: list) -> list:
        """Return the default fio arguments"""

        def remove_arg(args, item) -> list:
            if isinstance(item, str):
                return [arg for arg in args if arg != item]
            else:
                # We need to ensure that value based items are having the right value
                # This avoid a case where the user already defined a value we need to control
                i = 0
                while i < len(args):
                    arg = args[i]
                    removed = ""
                    if arg == item[0]:
                        removed = args.pop(i)
                        removed += " " + args.pop(i)
                    elif arg.startswith(f"{item[0]}="):
                        removed = args.pop(i)
                    if removed:
                        print(
                            f"{self.parameters.get_name_with_position()}: Fio parameter {item[0]} is now set to {item[1]} (was: {removed})"
                        )
                    else:
                        i += 1
                return args

        name = self.parameters.get_name_with_position()
        enforced_items = [
            ["--runtime", f"{self.parameters.get_runtime()}"],
            "--time_based",
            ["--output-format", "json+"],
            ["--numjobs", self.parameters.get_engine_instances_count()],
            ["--name", name],
            ["--invalidate", 1],
            ["--log_avg_msec", self.log_avg_msec],
        ]
        for log_type in ["bw", "lat", "hist", "iops"]:
            enforced_items.append([f"--write_{log_type}_log", f"fio/{name}_{log_type}.log"])

        for enforced_item in enforced_items:
            args = remove_arg(args, enforced_item)
            if isinstance(enforced_item, str):
                args.append(enforced_item)
            else:
                args.append(f"{enforced_item[0]}={enforced_item[1]}")

        return args

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        if self.skip:
            return self.parameters.get_result_format() | self.empty_result()
        try:
            ret = json.loads(stdout)
        except json.decoder.JSONDecodeError:
            print(f"{self.parameters.get_name_with_position()}: Cannot load fio's JSON output")
            print(f"stdout:\n{stdout.decode()}\nstderr:{stderr.decode()}")
            return self.parameters.get_result_format() | self.empty_result()

        return {"fio_results": ret} | self.parameters.get_result_format()

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name()

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)

    def empy_result(self):
        """Default empty results for fio"""
        return {
            "effective_runtime": 0,
            "skipped": self.skip,
            "fio_results": {"jobs": []},
        }


class FioCmdLine(Fio):
    def parse_parameters(self):
        """Removing fio arguments set by the engine"""
        # We need to ensure we have a proper fio command line
        # Let's remove duplicated and enforce some
        args = self.parameters.get_engine_module_parameter_base().split()

        # Overriding empb to represent the real executed command.
        # The list is having unique members and sorted to ensure a constant string representation.
        self.parameters.engine_module_parameter_base = " ".join(list(self.get_default_fio_command_line(args)))

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        return super().run_cmd() + self.parameters.get_engine_module_parameter_base().split()
