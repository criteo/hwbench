import datetime
import time
from datetime import timedelta
from typing import Optional
from ..utils import helpers as h
from .benchmark import Benchmark
from .monitoring import Monitoring
from .parameters import BenchmarkParameters
from ..environment.hardware import BaseHardware


class Benchmarks:
    """A class to list and execute benchmarks to run."""

    def __init__(self, out_dir, jobs_config, hardware: BaseHardware):
        self.jobs_config = jobs_config
        self.out_dir = out_dir
        self.benchs: list[Benchmark] = []
        self.hardware = hardware
        self.monitoring: Monitoring = None  # type: ignore[assignment]

    def get_engine(self, job):
        """Return the engine of a particular job."""
        # get the engine name
        engine_name = self.jobs_config.get_engine(job)
        try:
            # Are we able to instantiate a python object matching the engine name ?
            engine = self.jobs_config.load_engine(self.jobs_config.get_engine(job))
        except ModuleNotFoundError:
            h.fatal(f'Unknown "{engine_name}" engine')

        # extract the engine module associated to the engine
        engine_module_name = self.jobs_config.get_engine_module(job)
        if not engine_module_name:
            emn = engine_module_name
            h.fatal(f'Unknown "{emn}" engine_module for engine "{engine_name}"')

        return engine_name, engine.get_module(engine_module_name)

    def get_jobs_config(self):
        """Return the jobs_config."""
        return self.jobs_config

    def parse_jobs_config(self, validate_parameters=True):
        """Parse the jobs configuration file to create a list of benchmarks to run."""
        # Ensure the configuration file has a valid syntax
        self.jobs_config.validate_sections()

        # For each job in the jobs_config file
        for job in self.jobs_config.get_sections():
            # Get the engine for this job
            engine_name, engine_module = self.get_engine(job)

            # extract the engine module parameter
            engine_module_parameter = self.jobs_config.get_engine_module_parameter(job)

            for emp in engine_module_parameter:
                if emp not in engine_module.get_module_parameters(special_keywords=True):
                    h.fatal(f'Unknown "{emp}" engine_module_parameter for "{engine_name}"')

            # extract job's parameters
            stressor_range = self.jobs_config.get_stressor_range(job)
            stressor_range_scaling = self.jobs_config.get_stressor_range_scaling(job)
            hosting_cpu_cores_raw = self.jobs_config.get_hosting_cpu_cores(job)
            hosting_cpu_cores = hosting_cpu_cores_raw.copy()
            hosting_cpu_cores_scaling = self.jobs_config.get_hosting_cpu_cores_scaling(job)

            # Let's set the default values
            # If a single hosting_cpu_cores is set, the default scaling is iterate
            if len(hosting_cpu_cores) == 1:
                hosting_cpu_cores_scaling = "iterate"

            if (
                hosting_cpu_cores_scaling == "none"
                and isinstance(hosting_cpu_cores, list)
                and len(hosting_cpu_cores) > 0
                and isinstance(hosting_cpu_cores[0], list)
            ):
                h.fatal(
                    "Impossible to have multiple cpu cores lists in hosting_cpu_cores: "
                    f"{hosting_cpu_cores} ; with hosting_cpu_cores_scaling "
                    "strategy 'none'"
                )

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
                    h.fatal("hosting_cpu_cores is not module hosting_cpu_cores_scaling !")
                pinned_cpu = []
                while len(hosting_cpu_cores):
                    for step in range(steps):
                        for cpu in hosting_cpu_cores.pop():
                            pinned_cpu.append(cpu)
                    self.__schedule_benchmarks(
                        job,
                        stressor_range_scaling,
                        sorted(pinned_cpu.copy()),
                        validate_parameters,
                    )
            elif hosting_cpu_cores_scaling == "iterate":
                for iteration in range(len(hosting_cpu_cores)):
                    # Pick the last CPU of the list
                    pinned_cpu = hosting_cpu_cores.pop()
                    self.__schedule_benchmarks(job, stressor_range_scaling, pinned_cpu, validate_parameters)
            elif hosting_cpu_cores_scaling == "none":
                self.__schedule_benchmarks(
                    job,
                    stressor_range_scaling,
                    sorted(hosting_cpu_cores),
                    validate_parameters,
                )
            else:
                hccs = hosting_cpu_cores_scaling
                h.fatal(f"Unsupported hosting_cpu_cores_scaling : {hccs}")

    def __schedule_benchmarks(self, job, stressor_range_scaling, pinned_cpu, validate_parameters: bool):
        """Iterate on engine module parameters to schedule benchmarks."""
        # Detecting stressor range scaling mode
        if stressor_range_scaling == "plus_1":
            for emp in self.jobs_config.get_engine_module_parameter(job):
                self.__schedule_benchmark(job, pinned_cpu, emp, validate_parameters)
        else:
            srs = stressor_range_scaling
            h.fatal(f"Unsupported stressor_range_scaling : {srs}")

    def __schedule_benchmark(self, job, pinned_cpu, engine_module_parameter, validate_parameters: bool):
        """Schedule benchmark."""
        runtime = self.jobs_config.get_runtime(job)
        monitoring_config = self.get_monitoring_config(job)
        _, engine_module = self.get_engine(job)

        # If job needs monitoring, let's create it
        if monitoring_config != "none" and not self.monitoring:
            self.hardware.vendor.get_bmc().connect_redfish()
            self.hardware.vendor.get_bmc().detect()
            for pdu in self.hardware.vendor.get_pdus():
                pdu.connect_redfish()
                pdu.detect()
            self.monitoring = Monitoring(self.out_dir, self.jobs_config, self.hardware)

        # For each stressor, add a benchmark object to the list
        for stressor_count in self.jobs_config.get_stressor_range(job):
            if stressor_count == "auto":
                if pinned_cpu == "none":
                    h.fatal("stressor_range=auto but no pinned cpu")
                else:
                    if isinstance(pinned_cpu, int):
                        pinned_cpu = [pinned_cpu]
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
                        self.jobs_config.get_engine_module_parameter_base(job),
                        self.hardware,
                        monitoring_config,
                        self.monitoring,
                        self.jobs_config.get_skip_method(job),
                        self.jobs_config.get_sync_start(job),
                    )
                    benchmark = Benchmark(self.count_benchmarks(), engine_module, parameters)
                    self.add_benchmark(benchmark, validate_parameters)
            else:
                parameters = BenchmarkParameters(
                    self.out_dir,
                    job,
                    stressor_count,
                    pinned_cpu,
                    runtime,
                    engine_module_parameter,
                    self.jobs_config.get_engine_module_parameter_base(job),
                    self.hardware,
                    monitoring_config,
                    self.monitoring,
                    self.jobs_config.get_skip_method(job),
                    self.jobs_config.get_sync_start(job),
                )
                benchmark = Benchmark(self.count_benchmarks(), engine_module, parameters)
                self.add_benchmark(benchmark, validate_parameters)

    def add_benchmark(self, benchmark: Benchmark, validate_parameters: bool):
        if validate_parameters:
            benchmark.validate_parameters()
        self.benchs.append(benchmark)

    def count_benchmarks(self) -> int:
        return len(self.benchs)

    def count_jobs(self) -> int:
        """Return the number of jobs defined in the jobs_configuration file."""
        return len(self.jobs_config.get_sections())

    def get_benchmarks(self) -> list[Benchmark]:
        return self.benchs

    def runtime(self) -> int:
        """Return the overall runtime to run all jobs."""
        return sum(
            [
                benchmark.get_parameters().get_runtime()
                for benchmark in self.get_benchmarks()
                # Only count benchmarks that are not fully skipped
                if not benchmark.get_enginemodule().fully_skipped_job(benchmark.get_parameters())
            ]
        )

    def run(self):
        results = {}
        t = str(timedelta(seconds=self.runtime())).split(":")
        duration = f"{t[0]}h {t[1]}m {t[2]}s"
        print(
            f"hwbench: {self.count_jobs()} jobs, \
{self.count_benchmarks()} benchmarks, \
ETA {duration}"
        )
        # Run every benchmark of the list
        for benchmark in self.get_benchmarks():
            bench_name = benchmark.get_parameters().get_name()
            # This benchmark requires to be synced on a time based
            if benchmark.get_parameters().get_sync_start() == "time":
                time_to_sync_secs, _ = h.time_to_next_sync()
                print(f"hwbench: [{bench_name}]: sync_start=time requested, waiting {time_to_sync_secs} seconds")
                time.sleep(time_to_sync_secs)
                print(f"hwbench: [{bench_name}]: started at {datetime.datetime.utcnow()}")

            # Save each benchmark result
            results["{}_{}".format(benchmark.get_parameters().get_name(), benchmark.get_job_number())] = benchmark.run()
        return results

    def dump(self):
        with open(self.out_dir / "expanded_job_file.conf", "w") as f:
            for bench in self.benchs:
                engine = bench.get_enginemodule().get_engine()
                em = bench.get_enginemodule()
                param = bench.get_parameters()
                print(f"[{param.get_name()}_{bench.get_job_number()}]", file=f)
                print(f"runtime={param.get_runtime()}", file=f)
                print(f"monitoring={param.get_monitoring_config()}", file=f)
                print(f"engine={engine.get_name()}", file=f)
                print(f"engine_module={em.get_name()}", file=f)
                print(f"engine_binary={engine.get_binary()}", file=f)
                print(f"engine_binary_parameters={engine.run_cmd()}", file=f)
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
                print(f"stressor_instances={param.get_engine_instances_count()}", file=f)
                print(f"cmdline={' '.join(em.run_cmd(param))}", file=f)
                print("", file=f)

    def get_monitoring(self) -> Optional[Monitoring]:
        """Return the monitoring object"""
        return self.monitoring

    def get_monitoring_config(self, bench: Benchmark) -> str:
        """Return the monitoring configuration"""
        return self.jobs_config.get_monitor(bench)

    def need_monitoring(self):
        """Return if at least one bench requires monitoring"""
        return [bench.need_monitoring() for bench in self.benchs].count(True) > 0
