import pathlib
from .vendors.vendor import Temperature, ThermalContext
from .vendors.dell.dell import Dell
from .test_vendors import TestVendors, PATCH_TYPES

path = pathlib.Path("")


class TestDell(TestVendors):
    def __init__(self, *args, **kwargs):
        super().__init__(Dell("", None), *args, **kwargs)

    def setUp(self):
        # setUp is called by pytest to install patches
        # Prepare the vendor specifics
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.Dell.detect",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.run",
            PATCH_TYPES.RETURN_VALUE,
            True,
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_thermal",
            PATCH_TYPES.RETURN_VALUE,
            self.sample("tests/vendors/Dell/C6615/thermal"),
        )
        # And finish by calling the parent setUp()
        super().setUp()

    def test_thermal(self):
        expected_output = self.generic_thermal_output()
        expected_output[str(ThermalContext.INTAKE)] = {
            "Inlet Temp": Temperature("Inlet", 23)
        }
        expected_output[str(ThermalContext.CPU)] = {
            "CPU1 Temp": Temperature("CPU1", 34)
        }
        super().generic_thermal_test(expected_output)
