import pathlib
import json
import unittest
from unittest.mock import patch

from ..bench.parameters import BenchmarkParameters
from ..environment.mock import MockHardware
from .stressng import Engine as StressNG
from .stressng_qsort import EngineModuleQsort, StressNGQsort
from .stressng_memrate import EngineModuleMemrate, StressNGMemrate
from .stressng_stream import EngineModuleStream, StressNGStream
from .stressng_vnni import EngineModuleVNNI, StressNGVNNIMethods, StressNGVNNI


def mock_engine(version: str) -> StressNG:
    # We need to patch list_module_parameters() function
    # to avoid considering the local stress-ng binary
    with patch("hwbench.utils.helpers.is_binary_available") as iba:
        iba.return_value = True
        with patch("hwbench.engines.stressng_cpu.EngineModuleCpu.list_module_parameters") as p:
            p.return_value = (
                pathlib.Path(f"./hwbench/tests/parsing/stressngmethods/{version}/stdout").read_bytes().split(b":", 1)
            )
            return StressNG()


class TestParse(unittest.TestCase):
    def test_engine_parsing_version(self):
        test_dir = pathlib.Path("./hwbench/tests/parsing/stressng")
        for d in test_dir.iterdir():
            test_target = mock_engine("v17")
            if not d.is_dir():
                continue
            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()
            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_bytes().strip()

    def test_module_parsing_output(self):
        engine_v17 = mock_engine("v17")
        for classname, engine_module, prefix, instances, engine in [
            (StressNGQsort, EngineModuleQsort, "stressng", 0, engine_v17),
            (StressNGStream, EngineModuleStream, "stressng-stream", 0, engine_v17),
            (StressNGMemrate, EngineModuleMemrate, "stressng-memrate", 128, engine_v17),
        ]:
            test_dir = pathlib.Path(f"./hwbench/tests/parsing/{prefix}")
            for d in test_dir.iterdir():
                if not d.is_dir():
                    continue

                with self.subTest(f"prefix {prefix} dir {d}"):
                    # Mock elements
                    path = pathlib.Path("")
                    params = BenchmarkParameters(
                        path,
                        prefix,
                        instances,
                        "",
                        5,
                        "",
                        "",
                        MockHardware(),
                        "none",
                        None,
                        "bypass",
                        "none",
                    )
                    module = engine_module(engine, prefix)

                    # Class to test parse_cmd
                    test_target = classname(module, params)

                    # Populate version
                    ver_stdout = (d / "version-stdout").read_bytes()
                    test_target.parse_version(ver_stdout, None)

                    # Output of command to parse
                    stdout = (d / "stdout").read_bytes()
                    stderr = (d / "stderr").read_bytes()
                    output = test_target.parse_cmd(stdout, stderr)
                    # these are unused in parsing
                    for key in test_target.parameters.get_result_format().keys():
                        output.pop(key, None)
                    assert output == json.loads((d / "output").read_bytes())

    def test_stressng_methods(self):
        test_dir = pathlib.Path("./hwbench/tests/parsing/stressngmethods")
        for d in test_dir.iterdir():
            if not d.is_dir():
                continue

            print(f"parsing methods test {d.name}")
            test_target = mock_engine("v17").get_module("cpu")
            assert test_target

            output = test_target.get_module_parameters()
            assert output == json.loads((d / "output").read_bytes())

    def test_check_support(self):
        Intel_6140 = (
            "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 "
            "clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx pdpe1gb rdtscp "
            "lm constant_tsc art arch_perfmon pebs bts rep_good nopl xtopology "
            "nonstop_tsc cpuid aperfmperf pni pclmulqdq dtes64 monitor ds_cpl smx est "
            "tm2 ssse3 sdbg fma cx16 xtpr pdcm pcid dca sse4_1 sse4_2 x2apic movbe "
            "popcnt tsc_deadline_timer aes xsave avx f16c rdrand lahf_lm abm "
            "3dnowprefetch cpuid_fault epb cat_l3 cdp_l3 invpcid_single pti intel_ppin "
            "ssbd mba ibrs ibpb stibp fsgsbase tsc_adjust bmi1 hle avx2 smep bmi2 erms "
            "invpcid rtm cqm mpx rdt_a avx512f avx512dq rdseed adx smap clflushopt "
            "clwb intel_pt avx512cd avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves "
            "cqm_llc cqm_occup_llc cqm_mbm_total cqm_mbm_local dtherm ida arat pln pts "
            "hwp hwp_act_window hwp_pkg_req pku ospke md_clear flush_l1d "
            "arch_capabilities"
        ).split()
        AMD_9534 = (
            "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 "
            "clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm "
            "constant_tsc rep_good amd_lbr_v2 nopl nonstop_tsc cpuid extd_apicid "
            "aperfmperf rapl pni pclmulqdq monitor ssse3 fma cx16 pcid sse4_1 sse4_2 "
            "x2apic movbe popcnt aes xsave avx f16c rdrand lahf_lm cmp_legacy svm "
            "extapic cr8_legacy abm sse4a misalignsse 3dnowprefetch osvw ibs skinit "
            "wdt tce topoext perfctr_core perfctr_nb bpext perfctr_llc mwaitx cpb "
            "cat_l3 cdp_l3 invpcid_single hw_pstate ssbd mba perfmon_v2 ibrs ibpb "
            "stibp vmmcall fsgsbase bmi1 avx2 smep bmi2 erms invpcid cqm rdt_a avx512f "
            "avx512dq rdseed adx smap avx512ifma clflushopt clwb avx512cd sha_ni "
            "avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves cqm_llc cqm_occup_llc "
            "cqm_mbm_total cqm_mbm_local avx512_bf16 clzero irperf xsaveerptr rdpru "
            "wbnoinvd amd_ppin cppc arat npt lbrv svm_lock nrip_save tsc_scale "
            "vmcb_clean flushbyasid decodeassists pausefilter pfthreshold avic "
            "v_vmsave_vmload vgif x2avic v_spec_ctrl avx512vbmi umip pku ospke "
            "avx512_vbmi2 gfni vaes vpclmulqdq avx512_vnni avx512_bitalg "
            "avx512_vpopcntdq rdpid overflow_recov succor smca fsrm flush_l1d sev "
            "sev_es"
        ).split()
        AMD_7502 = (
            "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 "
            "clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm "
            "constant_tsc rep_good nopl nonstop_tsc cpuid extd_apicid aperfmperf rapl "
            "pni pclmulqdq monitor ssse3 fma cx16 sse4_1 sse4_2 movbe popcnt aes xsave "
            "avx f16c rdrand lahf_lm cmp_legacy svm extapic cr8_legacy abm sse4a "
            "misalignsse 3dnowprefetch osvw ibs skinit wdt tce topoext perfctr_core "
            "perfctr_nb bpext perfctr_llc mwaitx cpb cat_l3 cdp_l3 hw_pstate ssbd mba "
            "ibrs ibpb stibp vmmcall fsgsbase bmi1 avx2 smep bmi2 cqm rdt_a rdseed adx "
            "smap clflushopt clwb sha_ni xsaveopt xsavec xgetbv1 cqm_llc cqm_occup_llc "
            "cqm_mbm_total cqm_mbm_local clzero irperf xsaveerptr rdpru wbnoinvd "
            "amd_ppin arat npt lbrv svm_lock nrip_save tsc_scale vmcb_clean flushbyasid"
            " decodeassists pausefilter pfthreshold avic v_vmsave_vmload vgif "
            "v_spec_ctrl umip rdpid overflow_recov succor smca sev sev_es"
        ).split()

        def test_params(flags, method):
            hw = MockHardware(flags)
            return StressNGVNNIMethods().cpu_check(method, hw)

        def test_instance(flags, method):
            params = BenchmarkParameters(
                pathlib.Path(""),
                "test-" + method,
                0,
                "",
                5,
                method,
                "",
                MockHardware(flags),
                "none",
                None,
                "bypass",
                "none",
            )

            # Instantiate test, it should not fail
            StressNGVNNI(EngineModuleVNNI(mock_engine("v17"), "vnni"), params)

        assert test_params(Intel_6140, "noavx_vpaddb") is True
        assert test_params(Intel_6140, "avx_vpdpbusd512") is False
        assert test_params(Intel_6140, "avx_vpaddb128") is False
        assert test_params(Intel_6140, "avx_vpdpwssd512") is False

        assert test_params(AMD_9534, "noavx_vpaddb") is True
        assert test_params(AMD_9534, "avx_vpdpbusd512") is True
        assert test_params(AMD_9534, "avx_vpaddb128") is False

        assert test_params(AMD_7502, "noavx_vpaddb") is True
        assert test_params(AMD_7502, "avx_vpdpbusd512") is False
        assert test_params(AMD_7502, "avx_vpaddb128") is False
        assert test_params(AMD_7502, "avx_vpaddb256") is False

        with self.assertRaises(LookupError):
            test_instance(AMD_9534, "inexistant")
