import ast
import pathlib
import unittest
from unittest.mock import patch

from hwbench.bench.monitoring_structs import MonitoringContexts

from .vendors.bmc import BMC

VENDORS = pathlib.Path(__file__).parent / "tests/vendors"
TREE = VENDORS / "Generic/GPUServer/redfish_tree"


class TestBMCGpu(unittest.TestCase):
    def tree(self) -> dict:
        return ast.literal_eval(TREE.read_text())

    def sensors_only_tree(self) -> dict:
        """The same server, with a BMC exposing no accelerator as a Processor."""
        tree = self.tree()
        for suffix in ["", "?$expand=."]:
            tree[f"/redfish/v1/Systems/System.Embedded.1/Processors{suffix}"] = {
                "Members": [{"@odata.id": "/redfish/v1/Systems/System.Embedded.1/Processors/CPU.Socket.1"}]
            }
        return tree

    def served(self, tree: dict):
        """Patch the Redfish client with <tree>, recording every url requested."""
        requested: list[str] = []

        def get(url, log_failure=True):
            requested.append(url)
            # A url the tree does not hold is an unsupported request: that is
            # what get_redfish_url() returns for an error answer.
            return tree.get(url, {})

        return patch.object(BMC, "get_redfish_url", side_effect=get), requested

    def read_gpus(self, tree: dict) -> tuple[MonitoringContexts, list[str], BMC]:
        contexts = MonitoringContexts()
        bmc = BMC(pathlib.Path(""), None)
        patcher, requested = self.served(tree)
        with patcher:
            bmc.read_gpus(contexts)
        return contexts, requested, bmc

    def test_processor_metrics(self):
        contexts, _, _ = self.read_gpus(self.tree())

        assert contexts.Thermal["GPU"]["BMC_GPU_GPU1"].get_values() == [71.5]
        assert contexts.PowerConsumption.GPU["BMC_GPU_GPU1"].get_values() == [698.0]
        assert contexts.Utilization.GPU["BMC_GPU_GPU1"].get_values() == [99.4]
        assert contexts.Freq.GPU["BMC_GPU_GPU1"].get_values() == [1980.0]

        # GPU2 uses the deprecated ProcessorMetrics name and reports a subset:
        # the missing metrics must not be invented.
        assert contexts.Thermal["GPU"]["BMC_GPU_GPU2"].get_values() == [84.0]
        assert "BMC_GPU_GPU2" not in contexts.PowerConsumption.GPU
        assert "BMC_GPU_GPU2" not in contexts.Freq.GPU

    def test_sensors(self):
        contexts, _, _ = self.read_gpus(self.sensors_only_tree())

        assert contexts.PowerConsumption.GPU["BMC_GPU_GPU Subsystem Power"].get_values() == [1402.0]
        assert contexts.Thermal["GPU"]["BMC_GPU_GPU1 Inlet Temp"].get_values() == [38.0]
        # A voltage has no context to land in, and a CPU sensor is not ours.
        assert "BMC_GPU_GPU1 Voltage" not in contexts.PowerConsumption.GPU
        assert "BMC_GPU_CPU1 Temp" not in contexts.Thermal["GPU"]

    def test_sensors_skipped_when_processors_answer(self):
        """Walking every sensor of every chassis is the most expensive detection
        hwbench does: it must be skipped when ProcessorMetrics already describe
        the accelerators, more precisely."""
        contexts, requested, _ = self.read_gpus(self.tree())

        assert "BMC_GPU_GPU1" in contexts.PowerConsumption.GPU
        assert "BMC_GPU_GPU Subsystem Power" not in contexts.PowerConsumption.GPU
        assert not [url for url in requested if "Sensors" in url]

    def test_cpu_processors_are_ignored(self):
        contexts, _, _ = self.read_gpus(self.tree())
        assert "BMC_GPU_CPU.Socket.1" not in contexts.PowerConsumption.GPU

    def test_repeated_reads_append(self):
        """Sampling twice must append to the same metric, not recreate it."""
        contexts = MonitoringContexts()
        bmc = BMC(pathlib.Path(""), None)
        patcher, _ = self.served(self.tree())
        with patcher:
            bmc.read_gpus(contexts)
            bmc.read_gpus(contexts)
        assert contexts.PowerConsumption.GPU["BMC_GPU_GPU1"].get_values() == [698.0, 698.0]

    def test_no_gpu(self):
        """A BMC exposing no accelerator must report nothing, and say so."""
        contexts, _, bmc = self.read_gpus({})
        patcher, _ = self.served({})
        with patcher:
            assert bmc.has_gpus() is False
        assert contexts.PowerConsumption.GPU == {}
        assert contexts.Utilization.GPU == {}
        assert "GPU" not in contexts.Thermal

    def test_has_gpus(self):
        _, _, bmc = self.read_gpus(self.tree())
        patcher, _ = self.served(self.tree())
        with patcher:
            assert bmc.has_gpus() is True


class TestBMCExpand(unittest.TestCase):
    """$expand reads a whole collection in one request; it must degrade to one
    request per member whenever the service does not really support it."""

    def gpu_test(self) -> TestBMCGpu:
        return TestBMCGpu(methodName="test_sensors")

    def sensor_requests(self, tree: dict) -> tuple[list[str], MonitoringContexts]:
        """Read the GPU sensors of <tree> and return the urls requested for them."""
        helper = self.gpu_test()
        contexts, requested, _ = helper.read_gpus(tree)
        return [url for url in requested if "Sensors" in url], contexts

    def assert_sensors_were_read(self, contexts: MonitoringContexts) -> None:
        assert contexts.PowerConsumption.GPU["BMC_GPU_GPU Subsystem Power"].get_values() == [1402.0]
        assert contexts.Thermal["GPU"]["BMC_GPU_GPU1 Inlet Temp"].get_values() == [38.0]

    def test_expanded(self):
        """One request per collection, for the detection and for the reading."""
        tree = self.gpu_test().sensors_only_tree()
        requests, contexts = self.sensor_requests(tree)

        self.assert_sensors_were_read(contexts)
        assert all(url.endswith("$expand=.") for url in requests), requests
        # The 4 sensors of the collection cost 2 requests: one to detect them,
        # one to read them back.
        assert len(requests) == 2

    def test_fallback_when_not_advertised(self):
        """A service root without the capability must not even be asked."""
        tree = self.gpu_test().sensors_only_tree()
        del tree["/redfish/v1"]
        requests, contexts = self.sensor_requests(tree)

        self.assert_sensors_were_read(contexts)
        assert not [url for url in requests if "$expand" in url]

    def test_fallback_when_request_rejected(self):
        """A service advertising it but answering an error must be worked around."""
        tree = self.gpu_test().sensors_only_tree()
        del tree["/redfish/v1/Chassis/Chassis.1/Sensors?$expand=."]
        requests, contexts = self.sensor_requests(tree)

        self.assert_sensors_were_read(contexts)
        # It was tried, then every member was fetched individually.
        assert [url for url in requests if "$expand" in url]
        assert "/redfish/v1/Chassis/Chassis.1/Sensors/GPUSubsystemPwr" in requests

    def test_broken_expand_is_probed_once(self):
        """A service advertising it without honouring it must not be re-probed on
        every monitoring iteration."""
        helper = self.gpu_test()
        tree = helper.sensors_only_tree()
        collection = "/redfish/v1/Chassis/Chassis.1/Sensors"
        tree[f"{collection}?$expand=."] = tree[collection]

        contexts = MonitoringContexts()
        bmc = BMC(pathlib.Path(""), None)
        patcher, requested = helper.served(tree)
        with patcher:
            for _ in range(5):
                bmc.read_gpus(contexts)

        # Every tick was still read, through the per-member fallback.
        assert contexts.PowerConsumption.GPU["BMC_GPU_GPU Subsystem Power"].get_values() == [1402.0] * 5
        # Probed while detecting the sensors, then never again.
        assert len([url for url in requested if f"{collection}?$expand=." in url]) == 1

    def test_fallback_when_answer_is_not_expanded(self):
        """A service accepting the parameter and ignoring it must be detected."""
        tree = self.gpu_test().sensors_only_tree()
        collection = "/redfish/v1/Chassis/Chassis.1/Sensors"
        # The same answer as the unexpanded collection: references only.
        tree[f"{collection}?$expand=."] = tree[collection]
        requests, contexts = self.sensor_requests(tree)

        self.assert_sensors_were_read(contexts)
        assert "/redfish/v1/Chassis/Chassis.1/Sensors/GPU1Inlet" in requests


class TestBMCRealServers(unittest.TestCase):
    """Redfish trees trimmed from the dump of real GPU servers."""

    def read(self, model: str) -> tuple[MonitoringContexts, BMC, dict]:
        helper = TestBMCGpu(methodName="test_sensors")
        tree = ast.literal_eval((VENDORS / model / "redfish_tree").read_text())
        contexts, _, bmc = helper.read_gpus(tree)
        return contexts, bmc, tree

    def test_dell_xe9680(self):
        """The Dell BMC reports the 8 H200 through their ProcessorMetrics."""
        contexts, bmc, tree = self.read("Dell/XE9680")
        patcher, _ = TestBMCGpu(methodName="test_sensors").served(tree)
        with patcher:
            assert bmc.has_gpus() is True
            assert bmc.get_gpus_count() == 8

        assert len(contexts.PowerConsumption.GPU) == 8
        assert len(contexts.Thermal["GPU"]) == 8
        assert len(contexts.Utilization.GPU) == 8
        assert len(contexts.Freq.GPU) == 8
        gpu = "BMC_GPU_Video.Slot.28-1"
        assert contexts.Thermal["GPU"][gpu].get_values() == [72.0]
        assert contexts.PowerConsumption.GPU[gpu].get_values() == [606.4]
        assert contexts.Utilization.GPU[gpu].get_values() == [100.0]
        assert contexts.Freq.GPU[gpu].get_values() == [1770.0]
        # The CPUs are Processors too
        assert not [name for name in contexts.PowerConsumption.GPU if "CPU" in name]

    def test_hpe_xd685(self):
        """The HPE BMC lists the 8 B200 but exposes no metric of them: nothing is reported."""
        contexts, bmc, tree = self.read("Hpe/XD685")
        patcher, _ = TestBMCGpu(methodName="test_sensors").served(tree)
        with patcher:
            assert bmc.has_gpus() is False
        assert contexts.PowerConsumption.GPU == {}
        assert contexts.Utilization.GPU == {}
        assert "GPU" not in contexts.Thermal
