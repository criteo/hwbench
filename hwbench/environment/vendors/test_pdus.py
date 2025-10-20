import json
import pathlib

from hwbench.bench.monitoring_structs import Power, PowerContext
from hwbench.environment.test_vendors import PATCH_TYPES, TestVendors
from hwbench.environment.vendors.mock import MockVendor
from hwbench.environment.vendors.pdus.generic import Generic

path = pathlib.Path("")


class TestPDU(TestVendors):
    def __init__(self, path: str, *args, **kwargs):
        vendor = MockVendor(None, None)
        super().__init__(vendor, *args, **kwargs)
        self.pdu = Generic(vendor, "PDU_outlet")
        self.path = path

    def setUp(self):
        self.install_patch(
            "hwbench.environment.vendors.pdu.PDU.connect_redfish",
            PATCH_TYPES.RETURN_VALUE,
            None,
        )
        self.install_patch(
            "hwbench.environment.vendors.pdu.PDU.get_url",
            PATCH_TYPES.RETURN_VALUE,
            None,
        )
        self.install_patch(
            "hwbench.environment.vendors.vendor.Vendor.find_monitoring_sections",
            PATCH_TYPES.RETURN_VALUE,
            [],
        )
        self.install_patch(
            "hwbench.environment.vendors.pdus.generic.Generic.get_power_outlet",
            PATCH_TYPES.RETURN_VALUE,
            self.json(self.path + "outlet.json"),
        )
        self.install_patch(
            "hwbench.environment.vendors.pdus.generic.Generic.get_redfish_url",
            PATCH_TYPES.RETURN_VALUE,
            self.json(self.path + "pdu.json"),
        )
        self.get_vendor().prepare()

    def generic_power_output(self):
        return {str(PowerContext.PDU): {}}

    def generic_power_consumption_test(self, expected_output):
        return self.generic_test(expected_output, self.pdu.read_power_consumption({}))

    def json(self, name):
        with open(self.get_samples_file_name(name)) as file:
            return json.load(file)


class TestEnlogic(TestPDU):
    def __init__(self, *args, **kwargs):
        super().__init__("vendors/pdus/tests/enlogic/", *args, **kwargs)

    def test_outlet(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.PDU)] = {
            "PDU_outlet": Power("PDU_outlet", 0.0),
        }

        super().generic_power_consumption_test(expected_output)

    def test_pdu(self):
        self.pdu.detect()
        assert self.pdu.dump() == {
            "driver": "Generic",
            "firmware_version": "3.2.5",
            "model": "346-415V, 32A, 22.0kVA, 50/60Hz",
            "serial_number": "WPDXXXXX",
            "manufacturer": "ENLOGIC",
            "id": 1,
            "outlets": [{"id": "OUTLET 3", "name": "Outlet OUTLET 3, Branch Circuit A", "user_label": None}],
            "user_label": None,
        }


class TestRaritan(TestPDU):
    def __init__(self, *args, **kwargs):
        super().__init__("vendors/pdus/tests/raritan/", *args, **kwargs)

    def test_power(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.PDU)] = {
            "PDU_outlet": Power("PDU_outlet", 386.839),
        }

        super().generic_power_consumption_test(expected_output)

    def test_pdu(self):
        self.pdu.detect()
        assert self.pdu.dump() == {
            "driver": "Generic",
            "firmware_version": "4.3.0.5-51180",
            "id": "1",
            "manufacturer": "Raritan",
            "model": "PX3-5722V-V2",
            "outlets": [
                {
                    "id": "1",
                    "name": "Outlet 1",
                    "user_label": "A very nice outlet",
                },
            ],
            "serial_number": "1EXXXXXXXXXXX",
            "user_label": "DATACENTER-6/RACK-B37/FEED-C",
        }


class TestRaritanGroup(TestRaritan):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdu = Generic(self.vendor, "PDU_outletgroup")

    def setUp(self):
        super().setUp()
        self.install_patch(
            "hwbench.environment.vendors.pdus.generic.Generic.get_power_outlet",
            PATCH_TYPES.RETURN_VALUE,
            self.json(self.path + "outletgroup.json"),
        )

    def test_power(self):
        expected_output = self.generic_power_output()
        expected_output[str(PowerContext.PDU)] = {
            "PDU_outletgroup": Power("PDU_outletgroup", 825.9770000000001),
        }

        super().generic_power_consumption_test(expected_output)

    def test_pdu(self):
        self.pdu.detect()
        assert self.pdu.dump() == {
            "driver": "Generic",
            "firmware_version": "4.3.0.5-51180",
            "id": "1",
            "manufacturer": "Raritan",
            "model": "PX3-5722V-V2",
            "outlets": [
                {
                    "id": "2",
                    "name": "Serial xxx",
                    "user_label": None,
                },
            ],
            "serial_number": "1EXXXXXXXXXXX",
            "user_label": "DATACENTER-6/RACK-B37/FEED-C",
        }
