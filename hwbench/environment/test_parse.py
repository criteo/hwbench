import pathlib
import json

from . import cpu_cores
from . import cpu_info
from . import numa
from .vendors.amd import amd


class TestParseCPU(object):
    def test_ami_aptio(self):
        d = pathlib.Path("./tests/parsing/ami_aptio/v5")
        print(f"parsing test {d.name}")
        test_target = amd.Ami_Aptio("")
        ver_stdout = (d / "version-stdout").read_bytes()
        ver_stderr = (d / "version-stderr").read_bytes()
        version = test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (d / "version").read_bytes().strip()

    def test_parsing_cpuinfo(self):
        d = pathlib.Path("./tests/parsing/cpu_info/v2321")
        print(f"parsing test {d.name}")
        test_target = cpu_info.CPU_INFO("")

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
        d = pathlib.Path("./tests/parsing/cpu_cores/v2321")
        print(f"parsing test {d.name}")
        test_target = cpu_cores.CPU_CORES("")

        ver_stdout = (d / "version-stdout").read_bytes()
        ver_stderr = (d / "version-stderr").read_bytes()

        version = test_target.parse_version(ver_stdout, ver_stderr)
        assert version == (d / "version").read_bytes().strip()

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.get_physical_cores() == [
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
            29,
            30,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            44,
            45,
            46,
            47,
            48,
            49,
            50,
            51,
            52,
            53,
            54,
            55,
            56,
            57,
            58,
            59,
            60,
            61,
            62,
            63,
        ]
        assert test_target.get_hyperthread_cores() == [
            64,
            65,
            66,
            67,
            68,
            69,
            70,
            71,
            72,
            73,
            74,
            75,
            76,
            77,
            78,
            79,
            80,
            81,
            82,
            83,
            84,
            85,
            86,
            87,
            88,
            89,
            90,
            91,
            92,
            93,
            94,
            95,
            96,
            97,
            98,
            99,
            100,
            101,
            102,
            103,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            111,
            112,
            113,
            114,
            115,
            116,
            117,
            118,
            119,
            120,
            121,
            122,
            123,
            124,
            125,
            126,
            127,
        ]
        assert test_target.get_logical_cores_count() == 128
        assert test_target.get_physical_cores_count() == 64
        assert test_target.get_peer_siblings(0) == [0, 64]
        assert test_target.get_peer_sibling(0) == 64
        assert test_target.get_peer_sibling(64) == 0

    def test_parsing_numa_1_domain(self):
        d = pathlib.Path("./tests/parsing/numa/1domain")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA("")

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 1
        assert len(test_target.get_cores(0)) == 128

    def test_parsing_numa_4_domains(self):
        d = pathlib.Path("./tests/parsing/numa/4domains")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA("")

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 4
        for domain in range(0, test_target.count()):
            assert len(test_target.get_cores(domain)) == 16

    def test_parsing_numa_8_domains_with_llc(self):
        d = pathlib.Path("./tests/parsing/numa/8domainsllc")
        print(f"parsing test {d.name}")
        test_target = numa.NUMA("")

        stdout = (d / "stdout").read_bytes()
        stderr = (d / "stderr").read_bytes()

        test_target.parse_cmd(stdout, stderr)
        assert test_target.count() == 8
        for domain in range(0, test_target.count()):
            assert len(test_target.get_cores(domain)) == 16
