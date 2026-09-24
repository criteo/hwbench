import pathlib
from unittest.mock import patch

from hwbench.config import config

from . import benchmarks, cpumap
from . import test_benchmarks_common as tbc


class TestCpuMap(tbc.TestCommon):
    def load(self, cpu: str, numa: str):
        self.load_mocked_hardware(
            cpucores=f"./hwbench/tests/parsing/cpu_cores/{cpu}",
            cpuinfo=f"./hwbench/tests/parsing/cpu_info/{cpu}",
            numa=f"./hwbench/tests/parsing/numa/{numa}",
        )
        self.jobs_config = config.Config("./hwbench/config/cpumap.conf")
        self.jobs_config.set_hardware(self.hw)
        self.benches = benchmarks.Benchmarks(".", self.jobs_config, dry_run=True)
        self.benches.set_hardware(self.hw)
        # We need to patch list_module_parameters() function
        # to avoid considering the local stress-ng binary
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            p.return_value = (
                pathlib.Path("hwbench/tests/parsing/stressngmethods/v17/stdout").read_bytes().split(b":", 1)
            )
            self.parse_jobs_config()

    def test_dry_run_does_not_monitor(self):
        """A dry run must expand monitored jobs without connecting to the BMC or the PDUs."""
        with patch.object(benchmarks, "Monitoring") as monitoring:
            self.load("v2321", "8domainsllc")
        monitoring.assert_not_called()
        assert self.benches.get_monitoring() is None
        assert self.benches.count_benchmarks() == 7

    def test_map(self):
        """Check the map of an AMD EPYC 8534P: 64 physical cores, 8 NUMA domains, 4 quadrants."""
        self.load("v2321", "8domainsllc")
        lines = cpumap.render(self.benches).splitlines()
        # The legend comes first, and only lists the glyphs used by the maps
        assert lines[:7] == [
            "map legend: one column per physical core",
            "  #  all threads of the core are pinned",
            "  1  only its first thread is pinned",
            "  2  only its second thread is pinned",
            "  .  the core is not pinned",
            "  -  the benchmark is not pinned at all",
            "",
        ]
        assert lines[7] == (
            "AMD EPYC 8534P 64-Core Processor: 1 socket(s), 64 physical cores, 128 logical cpus, "
            "8 NUMA domains, 4 quadrants"
        )
        # A dry run gives the duration, not an end time: the run does not start now
        assert lines[8] == "hwbench: 3 jobs, 7 benchmarks, ETA 0h 07m 00s"
        assert lines[9] == ""
        # A separator as wide as the widest line, the job name centered on it, starts each job
        width = max(len(line) for line in lines)
        assert width == 130
        assert lines[10:] == [
            " [numa_domains] ".center(width, "="),
            "runtime = 2 benchmarks x 60s = 0h 02m 00s",
            "monitor=all",
            "stressor_range=auto",
            "stressor_range_scaling=plus_1",
            "selected_cpus=numa0 numa1",
            "selected_cpus_scaling=iterate",
            "skip_method=bypass",
            "sync_start=none",
            "engine=stressng",
            "engine_module=cpu",
            "engine_module_parameter=int64",
            "",
            "physical core   0       8       16      24      32      40      48      56    63  "
            "stressors  engine/module/parameter  logical cpus",
            "                |-------|-------|-------|-------|-------|-------|-------|------|",
            "numa domain     0000000011111111222222223333333344444444555555556666666677777777",
            "quadrant        0000000000000000111111111111111122222222222222223333333333333333",
            "numa_domains_0  ########........................................................"
            "         16  stressng/cpu/int64       0-7, 64-71",
            "numa_domains_1  ........########................................................"
            "         16  stressng/cpu/int64       8-15, 72-79",
            "",
            " [threads] ".center(width, "="),
            "runtime = 4 benchmarks x 60s = 0h 04m 00s",
            "monitor=all",
            "stressor_range=auto",
            "stressor_range_scaling=plus_1",
            "selected_cpus=core0-1",
            "selected_cpus_scaling=iterate",
            "skip_method=bypass",
            "sync_start=none",
            "engine=stressng",
            "engine_module=cpu",
            "engine_module_parameter=int64",
            "",
            "physical core   0       8       16      24      32      40      48      56    63  "
            "stressors  engine/module/parameter  logical cpus",
            "                |-------|-------|-------|-------|-------|-------|-------|------|",
            "numa domain     0000000011111111222222223333333344444444555555556666666677777777",
            "quadrant        0000000000000000111111111111111122222222222222223333333333333333",
            "threads_2       1..............................................................."
            "          1  stressng/cpu/int64       0",
            "threads_3       .1.............................................................."
            "          1  stressng/cpu/int64       1",
            "threads_4       2..............................................................."
            "          1  stressng/cpu/int64       64",
            "threads_5       .2.............................................................."
            "          1  stressng/cpu/int64       65",
            "",
            " [idle] ".center(width, "="),
            "runtime = 1 benchmark x 60s = 0h 01m 00s",
            "monitor=all",
            "stressor_range=1",
            "stressor_range_scaling=plus_1",
            "selected_cpus=none",
            "selected_cpus_scaling=iterate",
            "skip_method=bypass",
            "sync_start=none",
            "engine=sleep",
            "engine_module=sleep",
            "engine_module_parameter=sleep",
            "",
            "physical core   0       8       16      24      32      40      48      56    63  "
            "stressors  engine/module/parameter  logical cpus",
            "                |-------|-------|-------|-------|-------|-------|-------|------|",
            "numa domain     0000000011111111222222223333333344444444555555556666666677777777",
            "quadrant        0000000000000000111111111111111122222222222222223333333333333333",
            "idle_6          ----------------------------------------------------------------"
            "          1  sleep/sleep/sleep        no pinning",
        ]

    def test_map_split_per_socket(self):
        """A dual socket map too wide for the terminal is drawn as one block per socket."""
        self.load("cpustorage", "2domains")
        wide = cpumap.render(self.benches).splitlines()
        assert not any(line.startswith("physical core   18") for line in wide)
        assert (
            "numa_domains_0  ##################..................         36  stressng/cpu/int64       0-17, 36-53"
            in wide
        )

        narrow = cpumap.render(self.benches, width=80).splitlines()
        assert narrow.count("socket          000000000000000000") == 3
        assert narrow.count("socket          111111111111111111") == 3
        assert "numa_domains_0  ##################         36  stressng/cpu/int64       0-17, 36-53" in narrow
        assert "numa_domains_0  ..................         36  stressng/cpu/int64       0-17, 36-53" in narrow

    def test_graduation_ends_on_last_core(self):
        """The ruler always numbers and ticks the last core, whatever the core count."""
        assert cpumap.CpuMap.graduation(list(range(8))) == ("0      7", "|------|")
        assert cpumap.CpuMap.graduation(list(range(18, 36))) == ("18      26      35", "|-------|--------|")
        for count in range(1, 130):
            numbers, ticks = cpumap.CpuMap.graduation(list(range(count)))
            assert len(numbers) == len(ticks) == count
            assert numbers.endswith(str(count - 1))
            assert ticks.startswith("|")
            assert ticks.endswith("|")

    def test_job_runtime(self):
        """The runtime line gives the benchmark count, the runtime and the job duration."""
        self.load("v2321", "8domainsllc")
        lines = cpumap.render(self.benches).splitlines()
        # The runtime line of each job definition gives the duration of the whole job
        titles = [line for line in lines if line.startswith("runtime")]
        assert titles == [
            "runtime = 2 benchmarks x 60s = 0h 02m 00s",
            "runtime = 4 benchmarks x 60s = 0h 04m 00s",
            "runtime = 1 benchmark x 60s = 0h 01m 00s",
        ]

    def test_number_rows(self):
        """Numbers of 10 and more are written vertically, most significant digit first."""
        assert cpumap.number_rows([0, 1, 9], 1) == ["019"]
        assert cpumap.number_rows([0, 9, 10, 13, 19], 2) == ["00111", "09039"]
        assert cpumap.number_rows([7, None, 112], 3) == ["0?1", "0?1", "7?2"]

    def test_cut_empty_lines(self):
        """Long runs of empty lines keep their first and last lines around a "[...]" line."""
        full, empty = (False, "full"), (True, "empty")
        # Too short to be worth cutting
        assert cpumap.cut_empty_lines([full, empty, empty, empty, full]) == [
            "full",
            "empty",
            "empty",
            "empty",
            "full",
        ]
        lines = [full, (True, "first"), empty, empty, empty, (True, "last"), full]
        assert cpumap.cut_empty_lines(lines) == [
            "full",
            "first",
            "[...]",
            "last",
            "full",
        ]
        # A run ending the block is cut too
        assert cpumap.cut_empty_lines([full, *[empty] * 4])[-3:] == [
            "empty",
            "[...]",
            "empty",
        ]

    def test_legend(self):
        """The legend only lists what the maps use, "[...]" included."""
        assert cpumap.legend({"#", "."}) == [
            "map legend: one column per physical core",
            "  #  all threads of the core are pinned",
            "  .  the core is not pinned",
        ]
        # With SMT, every thread is explained, even if the maps only use the first one
        assert cpumap.legend({"#", "1", "."}, threads_per_core=2) == [
            "map legend: one column per physical core",
            "  #  all threads of the core are pinned",
            "  1  only its first thread is pinned",
            "  2  only its second thread is pinned",
            "  .  the core is not pinned",
        ]
        assert cpumap.legend({"#", "."}, cut=True) == [
            "map legend: one column per physical core",
            "  #      all threads of the core are pinned",
            "  .      the core is not pinned",
            "  [...]  benchmarks not pinned on this socket are not shown",
        ]
        self.load("cpustorage", "2domains")
        assert (
            "  [...]  benchmarks not pinned on this socket are not shown"
            not in cpumap.render(self.benches).splitlines()
        )
