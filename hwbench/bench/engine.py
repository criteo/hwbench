from __future__ import annotations

import abc
import pathlib
import subprocess
from enum import StrEnum
from typing import Any, Callable

from hwbench.utils.external import External
from hwbench.utils.helpers import (
    IncompatibleVersion,
    MissingBinary,
    english_env,
    is_binary_available,
    version_compatible,
)

from .parameters import BenchmarkParameters


class Resource(StrEnum):
    """A kind of component a benchmark loads."""

    CPU = "cpu"
    GPU = "gpu"
    DISK = "disk"


class EngineModuleBase(abc.ABC):
    def __init__(self, engine, name: str):
        """Please do not include initialization logic in this method, there is a dedicated init() method"""
        self.name = name
        self.engine: EngineBase = engine
        self.module_parameters: list[str] = []

    def get_engine(self):
        """Return the associated EngineBase."""
        return self.engine

    def get_name(self) -> str:
        return self.name

    def get_full_name(self, engine_module_parameter: str) -> str:
        """Return engine/engine_module/engine_module_parameter, as hwbench prints it."""
        return f"{self.engine.get_name()}/{self.get_name()}/{engine_module_parameter}"

    def add_module_parameter(self, name: str):
        if name not in self.get_module_parameters():
            self.module_parameters.append(name)

    def get_module_parameters(self, special_keywords=False):
        if special_keywords:
            return ["all"] + self.module_parameters
        return self.module_parameters

    def validate_module_parameters(self, params: BenchmarkParameters) -> str:
        return ""

    # Used to allow an engine to expand to a matrix of multiple benchmarks
    # Every entry is a dict containing custom parameters for each instance.
    # A 'workers' entry is consumed by Benchmarks to size the run instead of
    # being reported as a custom parameter.
    def generate_benchmarks(self, config: dict[str, str]) -> list[dict[str, Any]]:
        return [{}]

    def fully_skipped_job(self, p) -> bool:
        raise NotImplementedError

    def warmup(self, p: BenchmarkParameters) -> None:
        """One-off setup, run before the first benchmark is measured.

        Called for every benchmark before any of them starts, so an engine whose
        tool does expensive work on first use can get it out of the way instead
        of paying for it inside the monitored window of the first run. An engine
        doing this must make it idempotent: it is called once per benchmark, and
        Benchmarks instantiates one engine object per job.
        """

    def init(self):
        pass

    @abc.abstractmethod
    def run(self, params: BenchmarkParameters):
        pass


class EngineBase(External):
    # The kinds of component the benchmarks of this engine load. A class
    # attribute, so it is known without instantiating the engine: it decides
    # which requirements to check, how the GPUs are expanded and how the
    # benchmarks are reported, by hwbench and hwgraph alike.
    resources: tuple[Resource, ...] = ()
    # The oldest release of the binary this engine supports, checked before the
    # run starts; empty when any release goes.
    min_version = ""

    def __init__(self, name: str, binary: str, modules: dict[str, EngineModuleBase] | None = None):
        if modules is None:
            modules = {}
        External.__init__(self, pathlib.Path(""))
        self.engine_name = name
        self.binary = binary
        self.modules = modules
        self.version = ""
        self.custom_parameters_validators: dict[str, Callable[[str], str | None]] = {}
        self.custom_parameters_required: list[str] = []

    def get_binary(self) -> str:
        return self.binary

    def check_requirements(self) -> list[Exception]:
        if not is_binary_available(self.get_binary()):
            return [MissingBinary(self.binary)]
        if self.min_version:
            version = self.read_version()
            if not version_compatible(version, self.min_version):
                return [IncompatibleVersion(self.binary, version, self.min_version)]
        return []

    def read_version(self) -> str:
        """Run the version command of the binary and return the release it reports."""
        out = subprocess.run(self.run_cmd_version(), capture_output=True, env=english_env(), stdin=subprocess.DEVNULL)
        return self.parse_version(out.stdout, out.stderr)

    def init(self):
        for module in self.modules.values():
            module.init()

    def get_name(self) -> str:
        return self.engine_name

    @property
    def name(self) -> str:
        return self.get_name()

    def add_module(self, engine_module: EngineModuleBase):
        self.modules[engine_module.get_name()] = engine_module

    def get_modules(self) -> dict[str, EngineModuleBase]:
        return self.modules

    def get_module(self, module_name: str) -> EngineModuleBase | None:
        return self.modules.get(module_name)

    def module_exists(self, module_name) -> bool:
        return module_name in self.modules

    def get_version(self) -> str:
        return self.version
