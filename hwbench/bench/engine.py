import abc
import pathlib
from typing import Optional

from ..utils.external import External
from ..utils.helpers import fatal
from .parameters import BenchmarkParameters


class EngineModuleBase(abc.ABC):
    def __init__(self, engine, name: str):
        self.name = name
        self.engine = engine
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

    @abc.abstractmethod
    def run(self, params: BenchmarkParameters):
        pass


class EngineBase(External):
    def __init__(self, name: str, binary: str, modules: dict[str, EngineModuleBase] = {}):
        External.__init__(self, pathlib.Path(""))
        self.engine_name = name
        self.binary = binary
        self.modules = modules
        # FIXME: If the import is done at the file level, the mocking is lost here
        # So I'm importing is_binary_available just before the call :/
        from ..utils.helpers import is_binary_available

        if not is_binary_available(self.binary):
            fatal(f"Engine {name} requires '{binary}' binary, please install it.")

    def get_binary(self) -> str:
        return self.binary

    def get_name(self) -> str:
        return self.engine_name

    @property
    def name(self) -> str:
        return self.get_name()

    def add_module(self, engine_module: EngineModuleBase):
        self.modules[engine_module.get_name()] = engine_module

    def get_modules(self) -> dict[str, EngineModuleBase]:
        return self.modules

    def get_module(self, module_name: str) -> Optional[EngineModuleBase]:
        return self.modules.get(module_name)

    def module_exists(self, module_name) -> bool:
        return module_name in self.modules.keys()
