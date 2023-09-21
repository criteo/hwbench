from datetime import timedelta
from ..utils import helpers as h
from .benchmark import Benchmark
from .parameters import BenchmarkParameters
from ..environment.hardware import BaseHardware


class Benchmarks:
    """A class to list and execute benchmarks to run."""

    def __init__(self, out_dir, config, hardware: BaseHardware):
        self.config = config
        self.out_dir = out_dir
        self.benchs = []
        self.hardware = hardware

    def get_engine(self, job):
        """Return the engine of a particular job."""
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

        return engine_name, engine.get_module(engine_module_name)

    def parse_config(self):
        """Parse the configuration file to create a list of benchmarks to run."""
        # Ensure the configuration file has a valid syntax
        self.config.validate_sections()

        # For each job in the config file
        for job in self.config.get_sections():
            # Get the engine for this job
            engine_name, engine_module = self.get_engine(job)

            # extract the engine module parameter
            engine_module_parameter = self.config.get_engine_module_parameter(job)

            for emp in engine_module_parameter:
                if emp not in engine_module.get_module_parameters(
                    special_keywords=True
                ):
                    h.fatal(
                        f'Unknown "{emp}" engine_module_parameter for "{engine_name}"'
                    )

            # extract job's parameters
            stressor_range = self.config.get_stressor_range(job)
            stressor_range_scaling = self.config.get_stressor_range_scaling(job)
            hosting_cpu_cores_raw = self.config.get_hosting_cpu_cores(job)
            hosting_cpu_cores = hosting_cpu_cores_raw.copy()
            hosting_cpu_cores_scaling = self.config.get_hosting_cpu_cores_scaling(job)

            # Let's set the default values
            # If a single hosting_cpu_cores is set, the default scaling is iterate
            if len(hosting_cpu_cores) == 1:
                hosting_cpu_cores_scaling = "iterate"

            # if there is a single stressor, the scaling must be plus_1
            if len(stressor_range) == 1:
                stressor_range_scaling = "plus_1"

            # Reverse so the pop() call makes cores in a numerical order
            hosting_cpu_cores.reverse()

            # Let's create benchmark jobs
            # Detect hosting cpu cores scaling mode
            if hosting_cpu_cores_scaling.startswith("plus_"):
                steps = int(hosting_cpu_cores_scaling.replace("plus_", ""))
                # It's mandatory to have hosting_cpu_cores to be
                # a strict modulo of the requested steps
                # That would lead to an unbalanced benchmark configuration
                if len(hosting_cpu_cores) % steps != 0:
                    h.fatal(
                        "hosting_cpu_cores is not module hosting_cpu_cores_scaling !"
                    )
                pinned_cpu = []
                while len(hosting_cpu_cores):
                    for step in range(steps):
                        for cpu in hosting_cpu_cores.pop():
                            pinned_cpu.append(cpu)
                    self.__schedule_benchmarks(
                        job,
                        stressor_range_scaling,
                        pinned_cpu.copy(),
                    )
            elif hosting_cpu_cores_scaling == "iterate":
                for iteration in range(len(hosting_cpu_cores)):
                    # Pick the last CPU of the list
                    pinned_cpu = hosting_cpu_cores.pop()
                    self.__schedule_benchmarks(
                        job,
                        stressor_range_scaling,
                        pinned_cpu,
                    )
            else:
                hccs = hosting_cpu_cores_scaling
                h.fatal(f"Unsupported hosting_cpu_cores_scaling : {hccs}")

    def __schedule_benchmarks(
        self,
        job,
        stressor_range_scaling,
        pinned_cpu,
    ):
        """Iterate on engine module parameters to schedule benchmarks."""
        # Detecting stressor range scaling mode
        if stressor_range_scaling == "plus_1":
            for emp in self.config.get_engine_module_parameter(job):
                self.__schedule_benchmark(job, pinned_cpu, emp)
        else:
            srs = stressor_range_scaling
            h.fatal(f"Unsupported stressor_range_scaling : {srs}")

    def __schedule_benchmark(
        self,
        job,
        pinned_cpu,
        engine_module_parameter,
    ):
        """Schedule benchmark."""
        runtime = self.config.get_runtime(job)
        monitoring = self.config.get_monitor(job)
        _, engine_module = self.get_engine(job)
        # For each stressor, add a benchmark object to the list
        for stressor_count in self.config.get_stressor_range(job):
            if stressor_count == "auto":
                if pinned_cpu == "none":
                    h.fatal("stressor_range=auto but no pinned cpu")
                else:
                    stressor_count = len(pinned_cpu)
            if engine_module_parameter == "all":
                for individual_emp in engine_module.get_module_parameters():
                    parameters = BenchmarkParameters(
                        self.out_dir,
                        job,
                        stressor_count,
                        pinned_cpu,
                        runtime,
                        individual_emp,
                        self.config.get_engine_module_parameter_base(job),
                        self.hardware,
                        monitoring,
                    )
                    benchmark = Benchmark(
                        self.count_benchmarks(), engine_module, parameters
                    )
                    self.add_benchmark(benchmark)
            else:
                parameters = BenchmarkParameters(
                    self.out_dir,
                    job,
                    stressor_count,
                    pinned_cpu,
                    runtime,
                    engine_module_parameter,
                    self.config.get_engine_module_parameter_base(job),
                    self.hardware,
                    monitoring,
                )
                benchmark = Benchmark(
                    self.count_benchmarks(), engine_module, parameters
                )
                self.add_benchmark(benchmark)

    def add_benchmark(self, benchmark: Benchmark):
        self.benchs.append(benchmark)

    def count_benchmarks(self) -> int:
        return len(self.benchs)

    def count_jobs(self) -> int:
        """Return the number of jobs defined in the configuration file."""
        return len(self.config.get_sections())

    def get_benchmarks(self) -> list[Benchmark]:
        return self.benchs

    def runtime(self) -> int:
        """Return the overall runtime to run all jobs."""
        return sum(
            [
                benchmark.get_parameters().get_runtime()
                for benchmark in self.get_benchmarks()
            ]
        )

    def run(self):
        results = {}
        time = str(timedelta(seconds=self.runtime())).split(":")
        duration = f"{time[0]}h {time[1]}m {time[2]}s"
        print(
            f"hwbench: {self.count_jobs()} jobs, \
{self.count_benchmarks()} benchmarks, \
ETA {duration}"
        )
        # Run every benchmark of the list
        for benchmark in self.get_benchmarks():
            # Save each benchmark result
            results[
                "{}_{}".format(
                    benchmark.get_parameters().get_name(), benchmark.get_job_number()
                )
            ] = benchmark.run()
        return results

    def dump(self):
        with open(self.out_dir / "expanded_job_file.conf", "w") as f:
            for bench in self.benchs:
                engine = bench.get_enginemodule().get_engine()
                em = bench.get_enginemodule()
                param = bench.get_parameters()
                print(f"[{param.get_name()}_{bench.get_job_number()}]", file=f)
                print(f"runtime={param.get_runtime()}", file=f)
                print(f"monitoring={param.get_monitoring()}", file=f)
                print(f"engine={engine.get_binary()}", file=f)
                print(f"engine_module={em.get_name()}", file=f)
                print(f"engine_binary={engine.get_name()}", file=f)
                print(f"engine_binary_parameters={em.run_cmd(param)}", file=f)
                print(
                    f"engine_module_parameter={param.get_engine_module_parameter()}",
                    file=f,
                )
                print(
                    f"engine_module_parameter_base={param.get_engine_module_parameter_base()}",
                    file=f,
                )
                if param.get_pinned_cpu():
                    print(f"pinned_cpu={param.get_pinned_cpu()}", file=f)
                print(
                    f"stressor_instances={param.get_engine_instances_count()}", file=f
                )
                print("", file=f)
