import subprocess
from unittest.mock import patch

from hwbench.engines import pantheon
from hwbench.environment.mock import MockHardware

from . import test_benchmarks_common as tbc

# A fake 4 accelerators server.
FAKE_GPUS = tbc.fake_gpus(4)


class TestPantheon(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hw = MockHardware()
        self.load_benches("./hwbench/config/pantheon.conf")

    def test_gpu_scaling(self):
        self.parse_jobs_config(gpus=FAKE_GPUS)

        # burn_all_gpus : selected_gpus_scaling=none    -> 1 run on every GPU
        # burn_two_gpus : selected_gpus_scaling=iterate -> 1 run per GPU, per workload
        # gpu_ladder    : selected_gpus_scaling=curve   -> 1, 2, 3 then 4 GPUs
        # whole_suite   : parameter=all                 -> 1 run per workload of the suite
        assert self.get_benches().count_benchmarks() == 11
        assert self.get_benches().count_jobs() == 4

        self.assert_job(0, "burn_all_gpus", "core", "tensor_virus")
        assert self.gpu_list(0) == [0, 1, 2, 3]
        # One worker per loaded GPU
        assert self.get_bench_parameters(0).get_engine_instances_count() == 4

        # The GPU scaling is done for each workload
        for index, (test, gpu) in enumerate(
            [("fp64_virus", 0), ("tensor_virus", 0), ("fp64_virus", 1), ("tensor_virus", 1)],
            start=1,
        ):
            self.assert_job(index, "burn_two_gpus", "core", test)
            assert self.gpu_list(index) == [gpu]

        for index, gpus in enumerate([[0], [0, 1], [0, 1, 2], [0, 1, 2, 3]], start=5):
            self.assert_job(index, "gpu_ladder", "memory", "memory_read")
            assert self.gpu_list(index) == gpus

    def test_whole_suite(self):
        """'all' must run every workload of the suite, with the GPU selection."""
        self.parse_jobs_config(gpus=FAKE_GPUS)

        for index, test in enumerate(["rag_embedding", "vision_encoder"], start=9):
            self.assert_job(index, "whole_suite", "ai_auxiliary", test)
            # The GPU selection must survive the 'all' expansion.
            assert self.gpu_list(index) == [0, 1]
            assert self.get_bench_parameters(index).get_engine_instances_count() == 2

    def test_custom_parameters(self):
        """Custom parameters must reach the benchmark and the command line."""
        self.parse_jobs_config(gpus=FAKE_GPUS)

        params = self.get_bench_parameters(1)
        assert params.get_engine_module_parameter() == "fp64_virus"
        assert params.get_custom_parameters()["gpu_memory_percent"] == "50"
        assert params.get_custom_parameters()["verify"] == "false"

        engine_module = self.get_benches().get_benchmarks()[1].get_enginemodule()
        assert engine_module.run_cmd(params) == [
            "pantheon",
            "--test",
            "fp64_virus",
            "--duration",
            "30",
            "--mem",
            "50",
            "--gpu",
            "0",
            "--skip_verify",
        ]

    def test_kernels_are_compiled_before_the_first_run(self):
        """pantheon builds its kernels on first use, which must not be measured."""
        self.parse_jobs_config(gpus=FAKE_GPUS)

        pantheon.build_kernels.cache_clear()
        compiled = subprocess.CompletedProcess([], 0, b"", b"")
        with patch("subprocess.run", return_value=compiled) as run:
            for benchmark in self.get_benches().get_benchmarks():
                benchmark.get_enginemodule().warmup(benchmark.get_parameters())

        # Every benchmark asks, and the whole job file compiles once: the build
        # cache of pantheon is keyed on the platform, not on the workload.
        assert self.get_benches().count_benchmarks() > 1
        assert run.call_count == 1
        assert run.call_args[0][0] == [
            "pantheon",
            "--test",
            "baseline_metrics",
            "--duration",
            "1",
            # A warm up allocates no memory to speak of and skips the data
            # corruption check: it is only there to run the compiler.
            "--mem",
            "1",
            "--skip_verify",
        ]

    def test_kernels_are_compiled_once_per_platform(self):
        """The build cache is per platform, so each one has to be warmed up."""
        pantheon.build_kernels.cache_clear()
        compiled = subprocess.CompletedProcess([], 0, b"", b"")
        with patch("subprocess.run", return_value=compiled) as run:
            pantheon.build_kernels("pantheon", "mock")
            pantheon.build_kernels("pantheon", "mock")
            pantheon.build_kernels("pantheon", "cuda")
        assert run.call_count == 2
        assert run.call_args[0][0][-2:] == ["--platform", "cuda"]

    def test_a_failed_compilation_is_reported(self):
        """'make -k' can leave most workloads usable: warn, do not abort."""
        pantheon.build_kernels.cache_clear()
        failed = subprocess.CompletedProcess([], 2, b"nvcc: not found", b"")
        with patch("subprocess.run", return_value=failed), patch("builtins.print") as printed:
            pantheon.build_kernels("pantheon", "cuda")
        assert [call for call in printed.call_args_list if "WARNING" in str(call)]

    def test_no_gpu_detected(self):
        """A server without accelerator must not generate any benchmark."""
        self.should_be_fatal(lambda: self.parse_jobs_config(gpus={}))

    def test_unknown_gpu_is_fatal(self):
        """burn_two_gpus selects GPU 0 and 1, which a single GPU server does not have."""
        self.should_be_fatal(lambda: self.parse_jobs_config(gpus=tbc.fake_gpus(1)))


class TestRequirements(tbc.TestCommon):
    """all-smi finds the GPUs: it is required by the jobs loading them, and only by them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hw = MockHardware()

    def problems(self, job_file: str, binary: bool, version: str, gpus: dict) -> list[str]:
        self.load_benches(job_file)
        with (
            patch("hwbench.environment.all_smi.is_binary_available", return_value=binary),
            patch("hwbench.environment.all_smi.get_version", return_value=version),
            patch("hwbench.environment.all_smi.list_gpus", return_value=gpus),
        ):
            return [str(problem) for problem in self.get_benches().check_requirements() if "all-smi" in str(problem)]

    def test_gpu_job(self):
        assert self.problems("./hwbench/config/pantheon.conf", False, "", {}) == [
            "Binary all-smi is not available on the system"
        ]
        assert self.problems("./hwbench/config/pantheon.conf", True, "0.25.1", {}) == [
            "Binary all-smi 0.25.1 is too old, expecting >= 0.26.0"
        ]
        assert self.problems("./hwbench/config/pantheon.conf", True, "0.26.3", {}) == [
            "no accelerator reported by all-smi"
        ]
        assert self.problems("./hwbench/config/pantheon.conf", True, "0.26.3", FAKE_GPUS) == []

    def test_cpu_job(self):
        """A job not loading the GPUs does not need all-smi, nor any GPU."""
        assert self.problems("./hwbench/config/cpumap.conf", False, "", {}) == []


class TestPantheonFryer(tbc.TestCommon):
    """The shipped GPU soak job file, on a mocked 8 accelerators server."""

    FAKE_GPUS = tbc.fake_gpus(8)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="hwbench/tests/parsing/cpu_info/v2321",
            numa="hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./configs/full_gpu_load.conf")

    def test_fryer(self):
        """The soak must expand to the idle baseline plus one burn per workload."""
        self.parse_jobs_config(gpus=self.FAKE_GPUS)

        assert self.get_benches().count_jobs() == 3
        assert self.get_benches().count_benchmarks() == 8

        self.assert_job(0, "cool_down", "sleep")

        workloads = ["incinerator", "tensor_virus", "omni_virus", "pulse_virus", "voltage"]
        for index, test in enumerate(workloads, start=1):
            self.assert_job(index, "fry_cores", "core", test)

        for index, test in enumerate(["memory_thermal_asym", "memory_retention_bake"], start=6):
            self.assert_job(index, "fry_memory", "memory", test)

        # Every burn loads the whole server, for the whole runtime.
        for index in range(1, 8):
            assert self.gpu_list(index) == list(range(8))
            assert self.get_bench_parameters(index).get_runtime() == 360
