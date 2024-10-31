from ..bench.parameters import BenchmarkParameters
from .stressng import EngineBase, EngineModulePinnable, StressNG


class StressNGQsort(StressNG):
    """The StressNG Qsort CPU stressor."""

    def run_cmd(self) -> list[str]:
        # Let's build the command line to run the tool
        return super().run_cmd() + [
            "--qsort",
            str(self.parameters.get_engine_instances_count()),
        ]


class EngineModuleQsort(EngineModulePinnable):
    """This class implements the Qsort EngineModuleBase for StressNG"""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.add_module_parameter("qsort")

    def run_cmd(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return StressNGQsort(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return StressNGQsort(self, p).fully_skipped_job()
