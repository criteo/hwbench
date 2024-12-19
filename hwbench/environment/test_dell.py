import pathlib

from .test_vendors import PATCH_TYPES, TestVendors

path = pathlib.Path("")


class TestDell(TestVendors):
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
            self.sample(self.path + "thermal"),
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_power",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "power"),
        )
        self.install_patch(
            "hwbench.environment.vendors.dell.dell.IDRAC.get_oem_system",
            PATCH_TYPES.RETURN_VALUE,
            self.sample(self.path + "oem_system"),
        )
        # And finish by calling the parent setUp()
        super().setUp()
