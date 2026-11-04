"""Intel vendor implementation"""

from __future__ import annotations

import pathlib

from hwbench.environment.vendors.vendor import Vendor

from .intel_bmc import IntelBMC

# The Intel platforms supported, by their DMI product name lowercased: a new platform is added here
SUPPORTED_PLATFORMS = {
    "avenuecity",
}


class Intel(Vendor):
    """Intel vendor implementation"""

    def __init__(self, out_dir: pathlib.Path, dmi, monitoring_config_filename: str):
        super().__init__(out_dir, dmi, monitoring_config_filename)

    def detect(self) -> bool:
        """Detect a supported Intel platform"""
        if not self.dmi:
            return False
        # Intel Corporation also makes the NUCs and the desktop boards, which have no BMC:
        # only the platforms of SUPPORTED_PLATFORMS are Intel servers hwbench can monitor
        if self.dmi.info("sys_vendor") != "Intel Corporation":
            return False
        product = self.dmi.info("product_name") or ""
        return product.lower() in SUPPORTED_PLATFORMS

    def prepare(self):
        """Prepare Intel vendor"""
        if self.get_monitoring_config_filename():
            # Replace generic BMC with Intel-specific BMC before calling super().prepare()
            self.bmc = IntelBMC(self.out_dir, self)
            self.bmc.run()
        super().prepare()

    def save_bios_config(self):
        """Save the BIOS configuration, read through Redfish."""
        self.save_redfish_bios_config()

    def save_bmc_config(self):
        """Save the BMC configuration, read through Redfish."""
        self.save_redfish_bmc_config()

    def name(self) -> str:
        """Return vendor name"""
        return "Intel"
