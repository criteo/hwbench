from ..utils import helpers as h
from .benchmark import Benchmark, BenchmarkParameters


class Benchmarks:
    """A class to list and execute benchmarks to run."""

    def __init__(self, out_dir, config):
        self.config = config
        self.out_dir = out_dir
        self.benchs = []

    def parse_config(self):
        """Parse the configuration file to create a list of benchmarks to run."""
        # Ensure the configuration file has a valid syntax
        self.config.validate_sections()

        # For each job in the config file
        for job in self.config.get_sections():
            # get the engine name
            engine_name = self.config.get_engine(job)
            try:
                # Are we able to instantiate a python object matching the engine name ?
                engine = self.config.load_engine(self.config.get_engine(job))
            except ModuleNotFoundError:
                h.fatal(f'Unknown "{engine_name}" engine')

            # extract the engine module associated to the engine
            engine_module_name = self.config.get_engine_module(job)
            if not engine_module_name:
                emn = engine_module_name
                h.fatal(f'Unknown "{emn}" engine_module for engine "{engine_name}"')

            engine_module = engine.get_module(engine_module_name)

            # extract the engine module parameter
            engine_module_parameter = self.config.get_engine_module_parameter(job)
            if engine_module_parameter not in engine_module.get_module_parameters():
                emp = engine_module_parameter
                h.fatal(f'Unknown "{emp}" engine_module_parameter for "{engine_name}"')

            # extract job's parameters
            stressor_range = self.config.get_stressor_range(job)
            stressor_range_scaling = self.config.get_stressor_range_scaling(job)
            hosting_cpu_cores_raw = self.config.get_hosting_cpu_cores(job)
            hosting_cpu_cores = hosting_cpu_cores_raw.copy()
            hosting_cpu_cores_scaling = self.config.get_hosting_cpu_cores_scaling(job)
            runtime = self.config.get_runtime(job)

            # Let's set the default values
            # If a single hosting_cpu_cores is set, the default scaling is interate
            if len(hosting_cpu_cores) == 1:
                hosting_cpu_cores_scaling = "iterate"

            # if there is a single stressor, the scaling must be plus_1
            if len(stressor_range) == 1:
                stressor_range_scaling = "plus_1"

            # Reverse so the pop() call makes cores in a numerical order
            hosting_cpu_cores.reverse()

            # Let's create benchmark jobs
            # Detect hosting cpu cores scaling mode
            if hosting_cpu_cores_scaling == "iterate":
                for iteration in range(len(hosting_cpu_cores)):
                    # Pick the last CPU of the list
                    pinned_cpu = hosting_cpu_cores.pop()

                    # Detecting stressor range scaling mode
                    if stressor_range_scaling == "plus_1":
                        # For each stressor, add a benchmark object to the list
                        for stressor_count in self.config.get_stressor_range(job):
                            parameters = BenchmarkParameters(
                                self.out_dir,
                                job,
                                stressor_count,
                                pinned_cpu,
                                runtime,
                                engine_module_parameter,
                            )
                            benchmark = Benchmark(
                                self.count_benchmarks(), engine_module, parameters
                            )
                            self.add_benchmark(benchmark)
                    else:
                        srs = stressor_range_scaling
                        h.fatal(f"Unsupported stressor_range_scaling : {srs}")
            else:
                hccs = hosting_cpu_cores_scaling
                h.fatal(f"Unsupported hosting_cpu_cores_scaling : {hccs}")

    def add_benchmark(self, benchmark: Benchmark):
        self.benchs.append(benchmark)

    def count_benchmarks(self) -> int:
        return len(self.benchs)

    def get_benchmarks(self) -> list[Benchmark]:
        return self.benchs

    def run(self):
        results = {}
        # Run every benchmark of the list
        for benchmark in self.get_benchmarks():
            # Save each benchmark result
            results[
                "{}_{}".format(
                    benchmark.get_parameters().get_name(), benchmark.get_job_number()
                )
            ] = benchmark.run()
        return results
