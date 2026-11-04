import json
import pathlib
from unittest.mock import patch

import pytest

from hwbench.bench.monitoring_structs import Power, PowerConsumptionContext
from hwbench.environment.test_vendors import PATCH_TYPES, TestVendors
from hwbench.environment.vendors.mock import MockVendor
from hwbench.environment.vendors.monitoring_device import DeviceError, DeviceNotReady, MonitoringDevice
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
        return PowerConsumptionContext()

    def generic_power_consumption_test(self, expected_output):
        return self.generic_test(expected_output, self.pdu.read_power_consumption(PowerConsumptionContext()))

    def json(self, name):
        with open(self.get_samples_file_name(name)) as file:
            return json.load(file)


class TestEnlogic(TestPDU):
    def __init__(self, *args, **kwargs):
        super().__init__("vendors/pdus/tests/enlogic/", *args, **kwargs)

    def test_outlet(self):
        expected_output = self.generic_power_output()
        expected_output.PDU = {
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
        expected_output.PDU = {
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
        expected_output.PDU = {
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


def test_redfish_url_must_be_https():
    """A non https url is rejected, with the url in the message: no attempt would connect it."""
    device = MonitoringDevice(None)
    with pytest.raises(DeviceError) as error:
        device._connect_redfish("admin", "admin", "http://mypdu/", "session")
    assert str(error.value) == "redfish url 'http://mypdu/' must be an https url"
    assert not isinstance(error.value, DeviceNotReady)


def pdu_answering(answers: dict) -> Generic:
    """A PDU on outlets 1 and 2, answering <answers> by url; an absent url does not answer in time."""
    pdu = Generic(MockVendor(None, None), "PDU_outlet")
    pdu.outlet = "1,2"
    root = "/redfish/v1/PowerEquipment/RackPDUs/1/"

    def get(url, _args=None, max_retry=None):
        if url not in answers:
            # What python-redfish-library gives a single attempt not answered
            return None
        return type("Answer", (), {"dict": answers[url]})

    pdu.redfish_obj = type("Client", (), {"get": staticmethod(get)})
    answers.setdefault(root, {})
    return pdu


OUTLET = {"Id": "1", "Name": "Outlet", "PowerWatts": {"Reading": 100.0}}
OUTLETS = "/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/"


def test_pdu_not_answering_skips_the_reading():
    """An outlet not answering in time during the monitoring skips the reading: a PDU stopped hwbench on it."""
    pdu = pdu_answering({f"{OUTLETS}1": OUTLET})
    with patch.object(Generic, "get_url", return_value="https://pdu"):
        power = pdu.read_power_consumption(PowerConsumptionContext())
    # The power of the other outlet alone would be a wrong power of the server
    assert power.PDU["PDU_outlet"].get_values() == []
    assert pdu.timeouts == 1


@pytest.mark.parametrize(
    ("answers", "kind", "error"),
    [
        (
            {f"{OUTLETS}1": OUTLET},
            DeviceNotReady,
            "PDU PDU_outlet: https://pdu/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/2 did not answer in time",
        ),
        (
            {f"{OUTLETS}1": OUTLET, f"{OUTLETS}2": {}},
            DeviceError,
            "Cannot get outlet from url https://pdu/redfish/v1/PowerEquipment/RackPDUs/1/Outlets/2, please check its name: {}",
        ),
        (
            {f"{OUTLETS}1": OUTLET, f"{OUTLETS}2": {"Id": "2"}},
            DeviceError,
            "Outlet for https://pdu does not expose power metrics: {'Id': '2'}",
        ),
    ],
    ids=["timeout", "unknown outlet", "no power"],
)
def test_pdu_outlets_checked_at_startup(answers, kind, error):
    """The configuration of the outlets is checked when the PDU is detected: an outlet not answering in time
    may answer a later attempt, a wrong outlet never will."""
    pdu = pdu_answering(answers)
    with patch.object(Generic, "get_url", return_value="https://pdu"), pytest.raises(DeviceError) as raised:
        pdu.detect()
    assert error in str(raised.value)
    assert type(raised.value) is kind
