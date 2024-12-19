import pathlib
from unittest.mock import patch
from . import test_benchmarks_common as tbc
from .monitoring_structs import Metrics


class TestParse(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We need to patch list_module_parameters() function
        # to avoid considering the local stress-ng binary
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            print(pathlib.Path("."))
            p.return_value = (
                pathlib.Path("hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
            )
            self.load_mocked_hardware(
                cpucores="hwbench/tests/parsing/cpu_cores/v2321",
                cpuinfo="hwbench/tests/parsing/cpu_info/v2321",
                numa="hwbench/tests/parsing/numa/8domainsllc",
            )
            self.load_benches("./hwbench/config/sample.ini")
            self.parse_jobs_config()

    def test_parsing(self):
        assert self.benches.count_benchmarks() == 287
        assert self.benches.count_jobs() == 10
        assert self.benches.runtime() == 305

        # Checking if each jobs as the right number of subjobs
        self.assert_job(0, "check_1_core_int8_perf", "cpu", "int8")
        self.assert_job(1, "check_1_core_int8_float_perf", "cpu", "int8")
        self.assert_job(2, "check_1_core_int8_float_perf", "cpu", "float")
        self.assert_job(3, "check_1_core_qsort_perf", "qsort")

        # Checking if the first 64 jobs are check_all_cores_int8_perf
        for job in range(4, 68):
            self.assert_job(job, "check_all_cores_int8_perf", "cpu", "int8")

        # Checking if remaining jobs are int8_8cores_16stressors
        for job in range(68, 196):
            self.assert_job(job, "int8_8cores_16stressors", "cpu", "int8")

        for job in range(196, 199):
            self.assert_job(job, "check_physical_core_int8_perf", "cpu", "int8")
            # Ensure the auto syntax updated the number of engine instances
            if job == 198:
                instances = 4
            else:
                instances = 2
            assert self.get_bench_parameters(job).get_engine_instances_count() == instances

        group_count = 0
        for job in range(199, 203):
            group_count += 2
            self.assert_job(job, "check_physical_core_scale_plus_1_int8_perf", "cpu", "int8")  # noqa: E501
            assert self.get_bench_parameters(job).get_engine_instances_count() == group_count
            assert len(self.get_bench_parameters(job).get_pinned_cpu()) == group_count

        emp_all = self.get_benches().get_benchmarks()[203].get_enginemodule().get_module_parameters()
        emp_all.reverse()
        for job in range(203, 285):
            self.assert_job(job, "run_all_stressng_cpu", "cpu", emp_all.pop())

        assert self.get_bench_parameters(285).get_pinned_cpu() == list(range(0, 128))

        # Checking if the last job is sleep
        self.assert_job(-1, "sleep", "sleep")

    def test_monitoring(self):
        """Test if at least one benchmark needs monitoring."""
        # This jobs_config file needs monitoring
        assert self.benches.need_monitoring()
        monitoring = self.benches.get_monitoring()

        def get_monitoring_members(metric: Metrics):
            data = monitoring.get_metric(metric)
            return [len(data[pc]) for pc in data if len(data[pc]) > 0]

        assert get_monitoring_members(Metrics.FREQ)[0] == 48
        assert get_monitoring_members(Metrics.POWER_CONSUMPTION)[0] == 49

    def test_stream_short(self):
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            p.return_value = (
                pathlib.Path("./hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
            )
            self.load_benches("./hwbench/config/stream.ini")
            assert self.get_jobs_config().get_config().getint("global", "runtime") == 5
            self.get_jobs_config().get_config().set("global", "runtime", "2")
            with self.assertRaises(SystemExit):
                self.parse_jobs_config()
            # This jobs_config file doesn't need monitoring
            assert self.benches.need_monitoring() is False
