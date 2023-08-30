from ..utils.external import External


class EngineModuleBase:
    def __init__(self, engine, name: str):
        self.name = name
        self.engine = engine
        self.module_parameters = []

    def get_engine(self):
        """Return the associated EngineBase."""
        return self.engine

    def get_name(self) -> str:
        return self.name

    def add_module_parameter(self, name: str):
        if name not in self.get_module_parameters():
            self.module_parameters.append(name)

    def get_module_parameters(self):
        return self.module_parameters

    # params type unspecified to prevent import loop if we import BenchParameters
    def validate_module_parameters(self, params) -> str:
        return ""


class EngineBase(External):
    def __init__(self, name: str, binary: str, modules: dict[EngineModuleBase] = {}):
        External.__init__(self, "")
        self.engine_name = name
        self.binary = binary
        self.modules = modules

    def get_binary(self) -> str:
        return self.binary

    def get_name(self) -> str:
        return self.engine_name

    def run_cmd_version(self) -> list[str]:
        return NotImplementedError

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        return NotImplementedError

    def run_cmd(self) -> list[str]:
        return NotImplementedError

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return NotImplementedError

    def add_module(self, engine_module: EngineModuleBase):
        self.modules[engine_module.get_name()] = engine_module

    def get_modules(self) -> dict[EngineModuleBase]:
        return self.modules

    def get_module(self, module_name) -> EngineModuleBase:
        return self.modules.get(module_name)

    def module_exists(self, module_name) -> bool:
        return module_name in self.modules.keys()
