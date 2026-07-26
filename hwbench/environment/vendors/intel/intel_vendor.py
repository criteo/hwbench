"""Intel vendor implementation"""
from __future__ import annotations

import pathlib

from ..vendor import Vendor
from .intel_bmc import IntelBMC


class Intel(Vendor):
    """Intel vendor implementation"""

    def __init__(self, out_dir: pathlib.Path, dmi, monitoring_config_filename: str):
        super().__init__(out_dir, dmi, monitoring_config_filename)

    def detect(self) -> bool:
        """Detect if this is an Intel system"""
        if not self.dmi:
            return False
        
        # Check if manufacturer is Intel
        manufacturer = self.dmi.info("sys_vendor")
        product = self.dmi.info("product_name")
        
        if not manufacturer:
            return False
        
        manufacturer_lower = manufacturer.lower()
        product_lower = product.lower() if product else ""
        
        # Intel systems typically have "Intel" or "Intel Corporation" as manufacturer
        # or specific Intel product names like "Avenue City"
        is_intel = (
            "intel" in manufacturer_lower or
            "Intel Corporation" in manufacturer_lower or
            "AvenueCity" in product_lower or
            "intel server" in product_lower
        )
        
        return is_intel

    def prepare(self):
        """Prepare Intel vendor"""
        if self.get_monitoring_config_filename():
            # Replace generic BMC with Intel-specific BMC before calling super().prepare()
            self.bmc = IntelBMC(self.out_dir, self)
            self.bmc.run()
        super().prepare()

    def save_bios_config(self):
        """Save BIOS configuration"""
        print("Saving Intel BIOS configuration via Redfish")
        # TODO: Implement Intel-specific BIOS config dump via Redfish
        self.out_dir.joinpath("intel-bios-config").write_text("")

    def save_bmc_config(self):
        """Save BMC configuration"""
        print("Saving Intel BMC configuration via Redfish")
        # TODO: Implement Intel-specific BMC config dump via Redfish
        self.out_dir.joinpath("intel-bmc-config").write_text("")

    def name(self) -> str:
        """Return vendor name"""
        return "Intel"
