import pathlib

from .hpe.hpe import Hpe

from .vendor import Vendor
from .mock import MockVendor
from ..dmi import DmiSys


VENDOR_LIST = [
    Hpe,
]


def first_matching_vendor(out_dir: pathlib.Path, dmi: DmiSys) -> Vendor:
    for vendor in VENDOR_LIST:
        v = vendor(out_dir, dmi)
        if v.detect():
            return v
    return MockVendor(out_dir, dmi)
