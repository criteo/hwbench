from . import test_benchmarks_common as tbc


class TestFio(tbc.TestCommon):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_mocked_hardware(
            cpucores="./hwbench/tests/parsing/cpu_cores/v2321",
            cpuinfo="./hwbench/tests/parsing/cpu_info/v2321",
            numa="./hwbench/tests/parsing/numa/8domainsllc",
        )
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
            self.assertIsNone(bench.validate_parameters())
            bench.get_parameters().get_name() == "randread_cmdline"

        bench_0 = self.get_bench_parameters(0)
        assert (
            bench_0.get_engine_module_parameter_base()
            == "--bs=4k --direct=1 --filename=/dev/nvme0n1 --group_reporting \
--invalidate=1 --iodepth=256 --ioengine=libaio --log_avg_msec=20000 --name=randread_cmdline_0 \
--numjobs=4 --output-format=json+ --readonly --runtime=40 --rw=randread --time_based \
--write_bw_log=fio/randread_cmdline_0_bw.log --write_hist_log=fio/randread_cmdline_0_hist.log \
--write_iops_log=fio/randread_cmdline_0_iops.log --write_lat_log=fio/randread_cmdline_0_lat.log"
        )

        bench_1 = self.get_bench_parameters(1)
        assert (
            bench_1.get_engine_module_parameter_base()
            == "--bs=4k --direct=1 --filename=/dev/nvme0n1 --group_reporting \
--invalidate=1 --iodepth=256 --ioengine=libaio --log_avg_msec=20000 --name=randread_cmdline_1 \
--numjobs=6 --output-format=json+ --readonly --runtime=40 --rw=randread --time_based \
--write_bw_log=fio/randread_cmdline_1_bw.log --write_hist_log=fio/randread_cmdline_1_hist.log \
--write_iops_log=fio/randread_cmdline_1_iops.log --write_lat_log=fio/randread_cmdline_1_lat.log"
        )
