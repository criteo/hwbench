from collections.abc import Iterable
from typing import NamedTuple, Callable
from ..bench.parameters import BenchmarkParameters
from ..environment.hardware import BaseHardware
from .stressng import EngineBase, EngineModulePinnable, StressNG


class StressNGVNNIMethods:
    class Method(NamedTuple):
        check: Callable[[BaseHardware], bool]
        parameters: list[str]

    def __init__(self):
        M = StressNGVNNIMethods.Method

        def check_support(flag: str) -> Callable[[BaseHardware], bool]:
            def check(hw: BaseHardware) -> bool:
                return flag in hw.cpu_flags()

            return check

        # We don't enumerate with stress-ng --vnni-method list because we still need to
        # be able to check for compatibility.
        self.methods = {
            # tests generic methods
            "noavx_vpaddb": M(lambda _: True, ["--vnni-method", "vpaddb"]),
            "noavx_vpdpbusd": M(lambda _: True, ["--vnni-method", "vpdpbusd"]),
            "noavx_vpdpwssd": M(lambda _: True, ["--vnni-method", "vpdpwssd"]),
            # avx512 bw, relatively common
            "avx_vpaddb512": M(
                check_support("avx512bw"),
                ["--vnni-method", "vpaddb512", "--vnni-intrinsic"],
            ),
            # avx512 vnni, Xeon 3rd gen+ and Zen4 +
            "avx_vpdpbusd512": M(
                check_support("avx512_vnni"),
                ["--vnni-method", "vpdpbusd512", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd512": M(
                check_support("avx512_vnni"),
                ["--vnni-method", "vpdpwssd512", "--vnni-intrinsic"],
            ),
            # avx vnni, Xeon 4th gen+)
            "avx_vpaddb128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpaddb128", "--vnni-intrinsic"],
            ),
            "avx_vpaddb256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpaddb256", "--vnni-intrinsic"],
            ),
            "avx_vpdpbusd128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpbusd128", "--vnni-intrinsic"],
            ),
            "avx_vpdpbusd256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpbusd256", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd128": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpwssd128", "--vnni-intrinsic"],
            ),
            "avx_vpdpwssd256": M(
                check_support("avx_vnni"),
                ["--vnni-method", "vpdpwssd256", "--vnni-intrinsic"],
            ),
        }

    def enumerate(self) -> Iterable[str]:
        return self.methods.keys()

    def available(self, method: str) -> bool:
        return method in self.methods

    def cpu_check(self, method: str, hw: BaseHardware) -> bool:
        return self.methods[method].check(hw)

    def parameters(self, method: str) -> list[str]:
        for name, sm in self.methods.items():
            if name == method:
                return sm.parameters
        return []

    def enumerate_cpu(self, hw: BaseHardware) -> Iterable[str]:
        """list available methods for the cpu in hw"""
        return filter(lambda m: self.cpu_check(m, hw), self.enumerate())


class EngineModuleVNNI(EngineModulePinnable):
    """This class implements the VNNI EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.methods = StressNGVNNIMethods()
        for method in self.methods.enumerate():
            self.add_module_parameter(method)

    def fully_skipped_job(self, p) -> bool:
        return StressNGVNNI(self, p).fully_skipped_job()

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGVNNI(self, p).run()

    def validate_module_parameters(self, params: BenchmarkParameters):
        msg = super().validate_module_parameters(params)
        method = params.get_engine_module_parameter()
        if not self.methods.available(method):
            msg += f"Unknown method {method}\n"
        if not self.methods.cpu_check(method, params.get_hw()):
            print(f"WARNING: CPU does not support method {method}, perf will be 0")
        return msg


class StressNGVNNI(StressNG):
    def __init__(self, engine_module: EngineModuleVNNI, parameters: BenchmarkParameters):
        super().__init__(engine_module, parameters)
        self.method = parameters.get_engine_module_parameter()
        self.methods = engine_module.methods
        if not self.methods.available(self.method):
            raise LookupError(f"Unknown method {self.method}")
        if not self.methods.cpu_check(self.method, parameters.get_hw()):
            self.skip = True

    def run_cmd(self) -> list[str]:
        skip = self.need_skip_because_version()
        if skip:
            return skip
        return (
            super().run_cmd()
            + [
                "--vnni",
                str(self.parameters.get_engine_instances_count()),
            ]
            + self.methods.parameters(self.method)
        )

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return super().parse_cmd(stdout, stderr)
