from hwbench.utils.helpers import cpu_list_to_range

from . import test_benchmarks_common as tbc


class TestCores(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        self.load_benches("./hwbench/config/cores.conf")
        self.parse_jobs_config()

    def test_cores(self):
        """Check cores syntax."""
        CPU0 = [0, 64]
        CPU1 = [1, 65]
        CPU0_1 = sorted(CPU0 + CPU1)
        CPU0_7 = list(range(0, 8)) + list(range(64, 72))
        assert self.get_jobs_config().get_selected_cpus("cores") == [
            CPU0,
            CPU1,
            CPU0_7,
            CPU0_1,
        ]
        assert self.get_bench_parameters(0).get_pinned_cpu() == CPU0
        assert self.get_bench_parameters(1).get_pinned_cpu() == CPU1
        assert self.get_bench_parameters(2).get_pinned_cpu() == CPU0_7
        assert self.get_bench_parameters(3).get_pinned_cpu() == CPU0_1

        # Testing broken syntax that must fail
        self.load_benches("./hwbench/config/sample_weirds.conf")
        for test_name in [
            "invalid_cpu_core",
            "alpha_cpu_core",
        ]:
            self.should_be_fatal(self.get_jobs_config().get_selected_cpus, test_name)

    def test_core_input_types(self):
        """Check the various selected_cpus input types besides the CORE keyword."""
        self.load_benches("./hwbench/config/core_types.conf")
        self.parse_jobs_config()
        jc = self.get_jobs_config()

        # A single core-range group flattens into one cpu list...
        single_core_range = [0, 1, 2, 3, 64, 65, 66, 67]
        assert jc.get_selected_cpus("single_core_range") == single_core_range
        # Plain numeric logical cpus, without the CORE keyword.
        assert jc.get_selected_cpus("numeric_list") == [0, 1, 2, 3]
        # The 'all' keyword expands to every logical core.
        assert jc.get_selected_cpus("all_none") == list(range(128))
        # An explicit numeric list stays as-is.
        assert jc.get_selected_cpus("explicit_none") == [0, 2, 4]

        # ...and, with the default iterate scaling, produces one benchmark per
        # cpu, each pinned to a single-element list. cpu_list_to_range() must
        # render that single cpu (regression: it used to render an empty "").
        for index, cpu in enumerate(single_core_range):
            pinned = self.get_bench_parameters(index).get_pinned_cpu()
            assert pinned == [cpu]
            assert self.get_bench_parameters(index).get_engine_instances_count() == 1
            assert cpu_list_to_range(pinned) == str(cpu)

        # numeric_list follows single_core_range: 4 more single-cpu benchmarks.
        offset = len(single_core_range)
        for index, cpu in enumerate([0, 1, 2, 3]):
            assert self.get_bench_parameters(offset + index).get_pinned_cpu() == [cpu]

        # 'all' with scaling=none is a single benchmark pinned to every core.
        all_none = self.get_bench_parameters(offset + 4)
        assert all_none.get_pinned_cpu() == list(range(128))
        assert all_none.get_engine_instances_count() == 128
        assert cpu_list_to_range(all_none.get_pinned_cpu()) == "0-127"

        # explicit numeric list with scaling=none stays one non-contiguous group.
        explicit_none = self.get_bench_parameters(offset + 5)
        assert explicit_none.get_pinned_cpu() == [0, 2, 4]
        assert cpu_list_to_range(explicit_none.get_pinned_cpu()) == "0, 2, 4"
