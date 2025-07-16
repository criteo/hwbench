import json
import pathlib

from . import block_devices, cpu_cores, cpu_info, numa, nvme
from .vendors.amd import amd
from .vendors.vendor import BMC

path = pathlib.Path("")


class TestParseCPU:
    def test_ami_aptio(self):
        d = pathlib.Path("./hwbench/tests/parsing/ami_aptio/v5")
        print(f"parsing test {d.name}")
        test_target = amd.Ami_Aptio(path)
        ver_stdout = (d / "version-stdout").read_bytes()
        ver_stderr = (d / "version-stderr").read_bytes()
        version = test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (d / "version").read_bytes().strip()

    def test_parsing_cpuinfo(self):
        for d in [
            pathlib.Path("./hwbench/tests/parsing/cpu_info/v2321"),
            pathlib.Path("./hwbench/tests/parsing/cpu_info/cpustorage"),
        ]:
            print(f"parsing test {d.name}")
            test_target = cpu_info.CPU_INFO(path)

            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()

            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_bytes().strip()

            stdout = (d / "stdout").read_bytes()
            stderr = (d / "stderr").read_bytes()

            output = test_target.parse_cmd(stdout, stderr)
            assert output == json.loads((d / "output").read_bytes())

            assert test_target.get_arch() == output["Architecture"]
            assert test_target.get_family() == int(output["CPU family"])
            assert test_target.get_max_freq() == float(output["CPU max MHz"])
            assert test_target.get_model() == int(output["Model"])
            assert test_target.get_model_name() == output["Model name"]
            assert test_target.get_stepping() == int(output["Stepping"])
            assert test_target.get_vendor() == output["Vendor ID"]

    def test_parsing_cpu_cores(self):
        for d in [
            pathlib.Path("./hwbench/tests/parsing/cpu_cores/v2321"),
            pathlib.Path("./hwbench/tests/parsing/cpu_cores/cpustorage"),
            pathlib.Path("./hwbench/tests/parsing/cpu_cores/wsl"),
        ]:
            print(f"parsing test {d.name}")
            test_target = cpu_cores.CPU_CORES(d)

            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()

            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_bytes().strip()

            stdout = (d / "stdout").read_bytes()
            stderr = (d / "stderr").read_bytes()

            test_target.parse_cmd(stdout, stderr)

            if d.name == "v2321":
                assert test_target.get_physical_cores() == list(range(64))
                assert test_target.get_hyperthread_cores() == list(range(64, 128))
                assert test_target.get_logical_cores_count() == 128
                assert test_target.get_physical_cores_count() == 64
                assert test_target.get_peer_siblings(0) == [0, 64]
                assert test_target.get_peer_sibling(0) == 64
                assert test_target.get_peer_sibling(64) == 0

            if d.name == "cpustorage":
                assert test_target.get_physical_cores() == list(range(36))
                assert test_target.get_hyperthread_cores() == list(range(36, 72))
                assert test_target.get_logical_cores_count() == 72
                assert test_target.get_physical_cores_count() == 36
                assert test_target.get_peer_siblings(0) == [0, 36]
                assert test_target.get_peer_sibling(0) == 36

            if d.name == "wsl":
                assert test_target.get_physical_cores() == list(range(6))
                assert test_target.get_hyperthread_cores() == list(range(1, 12, 2))
                assert test_target.get_logical_cores_count() == 12
                assert test_target.get_physical_cores_count() == 6
                assert test_target.get_peer_siblings(0) == [0, 1]
                assert test_target.get_peer_sibling(0) == 1

    def test_parsing_numa_1_domain(self):
        d = pathlib.Path("./hwbench/tests/parsing/numa/1domain")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA(path)

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 1
        assert len(test_target.get_cores(0)) == 128

    def test_parsing_numa_2_domains(self):
        d = pathlib.Path("./hwbench/tests/parsing/numa/2domains")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA(path)

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 2
        assert len(test_target.get_cores(0)) == 36
        assert len(test_target.get_cores(1)) == 36

    def test_parsing_numa_4_domains(self):
        d = pathlib.Path("./hwbench/tests/parsing/numa/4domains")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA(path)

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 4
        for domain in range(0, test_target.count()):
            assert len(test_target.get_cores(domain)) == 16

    def test_parsing_numa_8_domains_with_llc(self):
        d = pathlib.Path("./hwbench/tests/parsing/numa/8domainsllc")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA(path)

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 8
        for domain in range(0, test_target.count()):
            assert len(test_target.get_cores(domain)) == 16


class TestParseIpmitool:
    def test_ipmitool_parsing(self):
        d = pathlib.Path("./hwbench/tests/parsing/ipmitool/1818")
        print(f"parsing test {d.name}")
        test_target = BMC(path, None)
        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()
        test_target.parse_cmd(stdout, stderr)
        assert test_target.get_url() == "https://10.168.97.137"


class TestParseNvme:
    def test_nvme_parsing_version_v116(self):
        d = pathlib.Path("./hwbench/tests/parsing/nvme/v116")
        print(f"parsing test {d.name}")
        test_target = nvme.Nvme(path)

        ver_stdout = (d / "version-stdout").read_bytes()
        ver_stderr = (d / "version-stderr").read_bytes()

        version = test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (d / "version").read_bytes().strip()


class TestParseSdparm:
    d = pathlib.Path("./hwbench/tests/parsing/sdparm/v110")
    test_target = block_devices.Sdparm(path, "/dev/sda")

    def test_sdparm_parsing_version_v110(self):
        print(f"parsing test {self.d.name}")

        ver_stdout = (self.d / "version-stdout").read_bytes()
        ver_stderr = (self.d / "version-stderr").read_bytes()

        version = self.test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (self.d / "version").read_bytes().strip()

    def test_parsing_sdparm_stdout_stderr(self):
        print(f"parsing test {self.d.name}")

        stdout = (self.d / "stdout").read_bytes()
        stderr = (self.d / "stderr").read_bytes()

        output = self.test_target.parse_cmd(stdout, stderr)

        assert output == json.loads((self.d / "output").read_bytes())


class TestParseSMART:
    d = pathlib.Path("./hwbench/tests/parsing/smartctl/v73")
    test_target = block_devices.Smartctl(path, "/dev/sda")

    def test_parsing_smartctl_version(self):
        print(f"parsing test {self.d.name}")

        ver_stdout = (self.d / "version-stdout").read_bytes()
        ver_stderr = (self.d / "version-stderr").read_bytes()

        version = self.test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (self.d / "version").read_bytes().strip()

    def test_parsing_smartctl_stdout_stderr(self):
        print(f"parsing test {self.d.name}")

        stdout = (self.d / "stdout").read_bytes()
        stderr = (self.d / "stderr").read_bytes()

        output = self.test_target.parse_cmd(stdout, stderr)

        assert output == json.loads((self.d / "output").read_bytes())
