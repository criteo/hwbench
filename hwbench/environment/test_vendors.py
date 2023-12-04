import ast
import errno
import pathlib
import os
import unittest
from enum import Enum
from unittest.mock import patch
from typing import Any  # noqa: F401
from .vendors.vendor import Vendor, ThermalContext


path = pathlib.Path("")


class PATCH_TYPES(Enum):
    # Different types of Patching
    SIDE_EFFECT = "side_effect"
    RETURN_VALUE = "return_value"


class TestVendors(unittest.TestCase):
    def __init__(self, vendor: Vendor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.patchers = {}  # type: dict[str, Any]
        self.vendor = vendor

    def get_vendor(self) -> Vendor:
        """Return the vendor object"""
        return self.vendor

    def get_patch(self, patcher):
        """Return a patch if already set."""
        return self.patchers.get(patcher)

    def install_patch(self, patcher, type: PATCH_TYPES, value, autostart=True):
        """Install one patch of PATCHERS and enable it by default."""

        # Adding a local helper if we need to make a side_effect patch
        def set_side_effect(side_function):
            self.patchers[patcher] = patch(str(patcher), side_effect=side_function)

        # Adding a local helper if we need to mock the return value
        def set_return_value(value):
            self.patchers[patcher] = patch(str(patcher), return_value=value)

        # Let's check if a patch is already installed
        current_patch = self.get_patch(patcher)
        # If so we stop it to install a new one
        if current_patch:
            current_patch.stop()

        if type == PATCH_TYPES.RETURN_VALUE:
            set_return_value(value)
        else:
            set_side_effect(value)

        if autostart:
            self.patchers[patcher].start()

    def setUp(self):
        # Setup is called by pytest to install patches
        # We put here the generic patches for all vendors
        # Vendors will override this function to add their specifics
        # Once done, they will this helper
        self.install_patch(
            "hwbench.environment.vendors.vendor.BMC.connect_redfish",
            PATCH_TYPES.RETURN_VALUE,
            None,
        )
        self.get_vendor().prepare()

    # tearDown is called at the end of the test
    def tearDown(self):
        # Let's stop all the installed patches
        patch.stopall()

    def sample(self, name):
        """Return the samples for this test."""
        output = None
        file = open(self.__get_samples_file_name(name), "r")
        output = file.readlines()
        # If the file is empty but json output is requested, let's return an empty string
        if not len(output):
            output = "{}"
        return ast.literal_eval("\n".join(output))

    def __get_samples_file_name(self, name):
        """Return the expected sample filename."""
        filename = ""
        # If there is no alternative set or alternative doesn't have this sample, let's use the default
        if not os.path.exists(filename):
            filename = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        if not os.path.exists(filename):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), filename)
        return filename

    def generic_thermal_output(self):
        return {
            str(ThermalContext.INTAKE): {},
            str(ThermalContext.CPU): {},
            str(ThermalContext.MEMORY): {},
            str(ThermalContext.SYSTEMBOARD): {},
            str(ThermalContext.POWERSUPPLY): {},
        }

    def generic_thermal_test(self, expected_output):
        vendor = self.get_vendor()
        thermals = vendor.get_bmc().read_thermals()
        for pc in thermals:
            if pc not in expected_output.keys():
                assert False, f"Missing Physical Context '{pc}' in expected_output"
            for sensor in thermals[pc]:
                if sensor not in expected_output[pc]:
                    assert False, f"Missing sensor '{sensor}' in '{pc}'"
                assert thermals[pc][sensor] == expected_output[pc][sensor]
