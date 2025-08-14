from __future__ import annotations

import abc
import pathlib

from hwbench.utils.external import External
from hwbench.utils.helpers import MissingBinary, is_binary_available

from .parameters import BenchmarkParameters


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

    def add_module_parameter(self, name: str):
        if name not in self.get_module_parameters():
            self.module_parameters.append(name)

    def get_module_parameters(self, special_keywords=False):
        if special_keywords:
            return ["all"] + self.module_parameters
        return self.module_parameters

    def validate_module_parameters(self, params: BenchmarkParameters) -> str:
        return ""

    def fully_skipped_job(self, p) -> bool:
        raise NotImplementedError

    def init(self):
        pass

    @abc.abstractmethod
    def run(self, params: BenchmarkParameters):
        pass


class EngineBase(External):
    def __init__(self, name: str, binary: str, modules: dict[str, EngineModuleBase] | None = None):
        if modules is None:
            modules = {}
        External.__init__(self, pathlib.Path(""))
        self.engine_name = name
        self.binary = binary
        self.modules = modules
        self.version = ""

    def get_binary(self) -> str:
        return self.binary

    def check_requirements(self) -> list[Exception]:
        if not is_binary_available(self.get_binary()):
            return [MissingBinary(self.binary)]
        return []

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
