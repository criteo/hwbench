from __future__ import annotations

import datetime
import time
from datetime import timedelta

from hwbench.bench.engine import EngineModuleBase
from hwbench.environment.hardware import BaseHardware
from hwbench.utils import helpers as h

from . import scaling
from .benchmark import Benchmark
from .monitoring import Monitoring
from .parameters import BenchmarkParameters


class Benchmarks:
    """A class to list and execute benchmarks to run."""

    def __init__(self, out_dir, jobs_config, verbose: bool = False, dry_run: bool = False) -> None:
        self.jobs_config = jobs_config
        self.out_dir = out_dir
        self.verbose = verbose
        self.dry_run = dry_run
        self.benchs: list[Benchmark] = []
        self.monitoring: Monitoring = None  # type: ignore[assignment]
        self.hardware: BaseHardware | None = None

    def set_hardware(self, hardware: BaseHardware):
        self.hardware = hardware

    def get_hardware(self) -> BaseHardware:
        if self.hardware is None:
            raise AttributeError("Hardware has not been previously set")
        return self.hardware

    def get_engine(self, job) -> tuple[str, EngineModuleBase]:
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

    def check_requirements(self) -> list[Exception]:
        """Check if all the binaries required by the benchmarks are present."""
        problems = []
        # For each job in the jobs_config file
        for job in self.jobs_config.get_sections():
            # Get the engine for this job
            _, engine_module = self.get_engine(job)
            if hasattr(engine_module.engine.__class__, "check_requirements") and callable(
                engine_module.engine.check_requirements
            ):
                problems += engine_module.engine.check_requirements()
        return problems

    def parse_jobs_config(self, validate_parameters=True):
        """Parse the jobs configuration file to create a list of benchmarks to run."""
        # Ensure the configuration file has a valid syntax
        self.jobs_config.validate_sections()

        # For each job in the jobs_config file
        for job in self.jobs_config.get_sections():
            # Get the engine for this job
            engine_name, engine_module = self.get_engine(job)
            engine_module.init()

            # extract the engine module parameter
            engine_module_parameter = self.jobs_config.get_engine_module_parameter(job)

            for emp in engine_module_parameter:
                if emp not in engine_module.get_module_parameters(special_keywords=True):
                    h.fatal(f'Unknown "{emp}" engine_module_parameter for "{engine_name}"')

            # extract job's parameters
            stressor_range_scaling = self.jobs_config.get_stressor_range_scaling(job)
            selected_cpus = self.jobs_config.get_selected_cpus(job)
            selected_cpus_scaling = self.jobs_config.get_selected_cpus_scaling(job)

            # Let's create benchmark jobs, one pinning per step of the cpu scaling
            for step in self.scaling(job, "selected_cpus_scaling", selected_cpus_scaling, selected_cpus):
                items = [selected_cpus[index] for index in step]
                if len(items) == 1:
                    # A single group, or a single cpu, as written
                    pinned_cpu = items[0]
                else:
                    # The step merges its groups, or its cpus
                    pinned_cpu = sorted(cpu for item in items for cpu in (item if isinstance(item, list) else [item]))
                self.__schedule_benchmarks(job, stressor_range_scaling, pinned_cpu, validate_parameters)

    def scaling(self, job: str, keyword: str, value: str, items: list) -> list[list[int]]:
        """Return the steps of a scaling, the job file being already validated."""
        try:
            return scaling.scaling(keyword, value, items, self.get_hardware().get_cpu())
        except ValueError as error:
            h.fatal(f"Job {job}: keyword {keyword}: {error}")

    def __schedule_benchmarks(self, job, stressor_range_scaling, pinned_cpu, validate_parameters: bool):
        """Iterate on engine module parameters to schedule benchmarks."""
        stressor_range = self.jobs_config.get_stressor_range(job)
        # Each step runs the stressor count of its last index, in the order they are written
        stressor_counts = [
            stressor_range[step[-1]]
            for step in self.scaling(job, "stressor_range_scaling", stressor_range_scaling, stressor_range)
        ]
        for emp in self.jobs_config.get_engine_module_parameter(job):
            self.__schedule_benchmark(job, pinned_cpu, emp, stressor_counts, validate_parameters)

    def __schedule_benchmark(
        self, job, pinned_cpu, engine_module_parameter, stressor_counts: list, validate_parameters: bool
    ):
        """Schedule benchmark."""
        runtime = self.jobs_config.get_runtime(job)
        monitoring_config = self.get_monitoring_config(job)
        _, engine_module = self.get_engine(job)
        engine_module.init()

        # If job needs monitoring, let's create it
        if monitoring_config != "none" and not self.monitoring and not self.dry_run:
            self.get_hardware().vendor.get_bmc().connect_redfish()
            self.get_hardware().vendor.get_bmc().detect()
            for pdu in self.get_hardware().vendor.get_pdus():
                pdu.connect_redfish()
                pdu.detect()
            self.monitoring = Monitoring(self.out_dir, self.jobs_config, self.get_hardware(), verbose=self.verbose)

        # For each stressor count, add a benchmark object to the list
        for stressor_count in stressor_counts:
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
                        self.get_hardware(),
                        monitoring_config,
                        self.monitoring,
                        self.jobs_config.get_skip_method(job),
                        self.jobs_config.get_sync_start(job),
                    )
                    benchmark = Benchmark(self.count_benchmarks(), engine_module, parameters)
                    self.add_benchmark(benchmark, validate_parameters)
            else:
                benchs = engine_module.generate_benchmarks(self.jobs_config.to_dict()[job])
                if benchs == []:
                    raise ValueError(f"No benchmarks generated for job {job}. Please check configuration")
                for bench in benchs:
                    parameters = BenchmarkParameters(
                        self.out_dir,
                        job,
                        stressor_count,
                        pinned_cpu,
                        runtime,
                        engine_module_parameter,
                        self.jobs_config.get_engine_module_parameter_base(job),
                        self.get_hardware(),
                        monitoring_config,
                        self.monitoring,
                        self.jobs_config.get_skip_method(job),
                        self.jobs_config.get_sync_start(job),
                        **bench,
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

    def runtime(self, job: str | None = None) -> int:
        """Return the overall runtime to run all jobs, or a single one."""
        return sum(
            [
                benchmark.get_parameters().get_runtime()
                for benchmark in self.get_benchmarks()
                if job is None or benchmark.get_parameters().get_name() == job
                # Only count benchmarks that are not fully skipped
                if not benchmark.get_enginemodule().fully_skipped_job(benchmark.get_parameters())
            ]
        )

    def summary(self, estimated_end: bool = True) -> str:
        """Return the number of jobs, benchmarks and the duration of the run.

        The estimated end time only makes sense when the run starts now.
        """
        duration = h.format_duration(self.runtime())
        summary = f"hwbench: {self.count_jobs()} jobs, {self.count_benchmarks()} benchmarks, ETA {duration}"
        if estimated_end:
            eta = datetime.datetime.now() + timedelta(seconds=self.runtime())
            summary += f", estimated end at {eta:%Y-%m-%d %H:%M:%S}"
        return summary

    def run(self):
        results = {}
        print(self.summary())
        # Run every benchmark of the list
        for benchmark in self.get_benchmarks():
            bench_name = benchmark.get_parameters().get_name()
            # This benchmark requires to be synced on a time based
            if benchmark.get_parameters().get_sync_start() == "time":
                time_to_sync_secs = h.time_to_next_sync()
                print(f"hwbench: [{bench_name}]: sync_start=time requested, waiting {time_to_sync_secs} seconds")
                time.sleep(time_to_sync_secs)
                print(f"hwbench: [{bench_name}]: started at {datetime.datetime.utcnow()}")

            # Save each benchmark result
            results[benchmark.get_parameters().get_name_with_position()] = benchmark.run()
        return results

    def dump(self):
        with open(self.out_dir / "expanded_job_file.conf", "w") as f:
            for bench in self.benchs:
                engine = bench.get_enginemodule().get_engine()
                em = bench.get_enginemodule()
                param = bench.get_parameters()
                print(f"[{param.get_name_with_position()}]", file=f)
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

    def get_monitoring(self) -> Monitoring | None:
        """Return the monitoring object"""
        return self.monitoring

    def get_monitoring_config(self, bench: Benchmark) -> str:
        """Return the monitoring configuration"""
        return self.jobs_config.get_monitor(bench)

    def need_monitoring(self):
        """Return if at least one bench requires monitoring"""
        return [bench.need_monitoring() for bench in self.benchs].count(True) > 0
