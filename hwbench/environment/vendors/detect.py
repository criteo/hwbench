import pathlib

from hwbench.environment.dmi import DmiSys

from .amd.amd import Amd
from .dell.dell import Dell
from .generic import GenericVendor
from .hpe.hpe import Hpe
from .vendor import Vendor

VENDOR_LIST = [
    Dell,
    Hpe,
    Amd,
    # This one always detects the hardware and should be kept at the end
    GenericVendor,
]


def first_matching_vendor(out_dir: pathlib.Path, dmi: DmiSys, monitoring_config_filename) -> Vendor:
    for vendor in VENDOR_LIST:
        v = vendor(out_dir, dmi, monitoring_config_filename)  # type: ignore
        if v.detect():
            # If the vendor matched, it may need to prepare some stuff
            v.prepare()
            return v
    raise AssertionError("Unreachable: the GenericVendor should have been selected")
