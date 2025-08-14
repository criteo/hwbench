from unittest.mock import patch

from . import test_benchmarks_common as tbc


class TestFio(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
        with patch("hwbench.engines.fio.Engine.validate_disks", return_value=None):
            self.load_benches("./hwbench/config/fio.conf")
            self.parse_jobs_config()
        self.QUADRANT0 = list(range(0, 16)) + list(range(64, 80))
        self.QUADRANT1 = list(range(16, 32)) + list(range(80, 96))
        self.ALL = list(range(0, 128))

    def test_fio(self):
        """Check fio syntax."""
        assert self.benches.count_benchmarks() == 2
        assert self.benches.count_jobs() == 1
        assert self.benches.runtime() == 80

        for bench in self.benches.benchs:
            assert bench.validate_parameters() is None
            assert bench.get_parameters().get_name() == "randread_cmdline"

        bench_0 = self.get_bench_parameters(0)
        assert (
            bench_0.get_engine_module_parameter_base()
            == "--direct=1 --rw=randread --bs=4k --ioengine=libaio --iodepth=256 --group_reporting --readonly --runtime=40 --time_based --output-format=json+ --numjobs=4 --name=randread_cmdline_0 --invalidate=1 --log_avg_msec=20000 --filename=/dev/nvme0n1 --write_bw_log=fio/randread_cmdline_0_bw.log --write_lat_log=fio/randread_cmdline_0_lat.log --write_hist_log=fio/randread_cmdline_0_hist.log --write_iops_log=fio/randread_cmdline_0_iops.log"
        )

        bench_1 = self.get_bench_parameters(1)
        assert (
            bench_1.get_engine_module_parameter_base()
            == "--direct=1 --rw=randread --bs=4k --ioengine=libaio --iodepth=256 --group_reporting --readonly --runtime=40 --time_based --output-format=json+ --numjobs=6 --name=randread_cmdline_1 --invalidate=1 --log_avg_msec=20000 --filename=/dev/nvme0n1 --write_bw_log=fio/randread_cmdline_1_bw.log --write_lat_log=fio/randread_cmdline_1_lat.log --write_hist_log=fio/randread_cmdline_1_hist.log --write_iops_log=fio/randread_cmdline_1_iops.log"
        )
