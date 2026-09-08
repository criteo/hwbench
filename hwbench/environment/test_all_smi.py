import json
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from hwbench.bench.monitoring_structs import MonitoringContexts

from .all_smi import AllSMI, AllSMIMonitoring, gpu_inventory, parse_frame, parse_version

TEST_DIR = pathlib.Path("./hwbench/tests/parsing/all-smi")
# The 3 H100 of the fixture: two loaded, one idle.
H100 = TEST_DIR / "v0263-h100" / "stdout"
# An integrated GPU whose driver exposes no power, no clock and no temperature.
ARC = TEST_DIR / "v0263-arc" / "stdout"


class TestAllSMI(unittest.TestCase):
    def test_parsing(self):
        for d in TEST_DIR.iterdir():
            if not d.is_dir():
                continue

            with self.subTest(f"all-smi dir {d}"):
                test_target = AllSMI(d)

                version = test_target.parse_version((d / "version-stdout").read_bytes(), b"")
                assert version == (d / "version").read_text().strip()

                output = test_target.parse_cmd((d / "stdout").read_bytes(), (d / "stderr").read_bytes())
                assert output == json.loads((d / "output").read_bytes())

    def test_no_output(self):
        """all-smi writes nothing when the host has no accelerator."""
        assert AllSMI(pathlib.Path("")).parse_cmd(b"", b"") == {}

    def test_unsupported_schema(self):
        """A schema we do not know must report no accelerator, not a wrong one."""
        frame = {"schema": 2, "gpus": [{"uuid": "GPU-0"}]}
        assert AllSMI(pathlib.Path("")).parse_cmd(json.dumps(frame).encode(), b"") == {}

    def test_vendor_detail_is_kept_verbatim(self):
        """The vendor properties are reported as all-smi named them."""
        gpus = AllSMI(pathlib.Path("")).parse_cmd(H100.read_bytes(), b"")
        assert gpus["0"]["detail"]["Driver Version"] == "580.65.06"
        assert gpus["0"]["detail"]["power_limit_current"] == "700.00"

    def test_vendor_detail_is_unquoted(self):
        """The NVIDIA backend keeps the quotes nvidia-smi prints around the VBIOS version."""
        frame = {"schema": 1, "gpus": [{"uuid": "GPU-0", "detail": {"vbios_version": '"97.00.FA.00.02"'}}]}
        gpus = AllSMI(pathlib.Path("")).parse_cmd(json.dumps(frame).encode(), b"")
        assert gpus["0"]["detail"]["vbios_version"] == "97.00.FA.00.02"

    def test_version(self):
        assert parse_version(b"all-smi 0.26.3\n") == "0.26.3"


class TestAllSMIMonitoring(unittest.TestCase):
    def monitoring(self) -> tuple[MonitoringContexts, AllSMIMonitoring]:
        contexts = MonitoringContexts()
        inventory = gpu_inventory(parse_frame(json.loads(H100.read_bytes())))
        return contexts, AllSMIMonitoring(contexts, inventory)

    def sample(self, monitoring: AllSMIMonitoring, frame: dict) -> None:
        """Sample one frame, as if the exporter had served it."""
        with (
            # A running exporter: poll() is None as long as it lives.
            patch.object(monitoring, "process", MagicMock(**{"poll.return_value": None})),
            patch.object(monitoring, "get_frame", return_value=frame),
        ):
            monitoring.sample()

    def test_metrics_initialization(self):
        contexts, _ = self.monitoring()
        for index in range(3):
            name = f"GPU_{index}"
            assert contexts.PowerConsumption.GPU[name].get_unit() == "Watts"
            assert contexts.Freq.GPU[name].get_unit() == "Mhz"
            assert contexts.Utilization.GPU[name].get_unit() == "Percent"
            assert contexts.Memory.GPU[name].get_unit() == "MiB"
            assert contexts.Thermal["GPU"][name].get_unit() == "Celsius"

    def test_sampling(self):
        contexts, monitoring = self.monitoring()
        self.sample(monitoring, json.loads(H100.read_bytes()))

        assert contexts.PowerConsumption.GPU["GPU_0"].get_values() == [698.21]
        assert contexts.Freq.GPU["GPU_1"].get_values() == [1432.0]
        assert contexts.Utilization.GPU["GPU_1"].get_values() == [100.0]
        assert contexts.Thermal["GPU"]["GPU_2"].get_values() == [38.0]
        # 82005983232 bytes, reported in MiB like the CPU memory is.
        assert contexts.Memory.GPU["GPU_0"].get_values() == [78207.0]
        # An idle accelerator holds no memory and that is a value, not a hole.
        assert contexts.Memory.GPU["GPU_2"].get_values() == [0.0]
        assert contexts.Utilization.GPU["GPU_2"].get_values() == [0.0]

    def test_unreadable_sensors_are_not_reported_as_zero(self):
        """all-smi reports an unsupported sensor as 0, which is not a reading."""
        contexts = MonitoringContexts()
        inventory = gpu_inventory(parse_frame(json.loads(ARC.read_bytes())))
        monitoring = AllSMIMonitoring(contexts, inventory)
        self.sample(monitoring, json.loads(ARC.read_bytes()))

        assert contexts.PowerConsumption.GPU["GPU_0"].get_values() == []
        assert contexts.Freq.GPU["GPU_0"].get_values() == []
        assert contexts.Thermal["GPU"]["GPU_0"].get_values() == []
        # Those two are legitimately 0 on an idle integrated GPU.
        assert contexts.Utilization.GPU["GPU_0"].get_values() == [0.0]
        assert contexts.Memory.GPU["GPU_0"].get_values() == [0.0]

    def test_unknown_accelerator_is_ignored(self):
        """An accelerator that was not inventoried has no metric to fill."""
        contexts, monitoring = self.monitoring()
        frame = json.loads(H100.read_bytes())
        frame["gpus"] = [dict(frame["gpus"][0], uuid="GPU-hotplugged")] * 4
        self.sample(monitoring, frame)

        # The 3 inventoried positions are filled by their position, the 4th has
        # neither a known uuid nor a known position.
        assert len(contexts.PowerConsumption.GPU["GPU_0"].get_values()) == 1
        assert len(contexts.PowerConsumption.GPU["GPU_2"].get_values()) == 1
        assert "GPU_3" not in contexts.PowerConsumption.GPU

    def test_sampling_without_exporter_is_not_fatal(self):
        contexts, monitoring = self.monitoring()
        monitoring.sample()
        assert contexts.PowerConsumption.GPU["GPU_0"].get_values() == []
