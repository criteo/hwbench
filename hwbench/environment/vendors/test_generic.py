from __future__ import annotations

from unittest.mock import patch

import pytest

from hwbench.environment.vendors.bmc import BMC
from hwbench.environment.vendors.generic import GenericVendor
from hwbench.environment.vendors.mock import MockedBMC

LOCATION = "[Location]\nCountry=FR\n"
BMC_SECTION = "[default]\nusername=admin\npassword=secret\ntype=BMC\n"


@pytest.mark.parametrize(
    ("environment", "expected_bmc"),
    [
        (None, MockedBMC),
        (LOCATION, MockedBMC),
        (LOCATION + BMC_SECTION, BMC),
    ],
)
def test_bmc(tmp_path, environment, expected_bmc):
    environment_file = ""
    if environment is not None:
        environment_file = str(tmp_path / "environment.cfg")
        (tmp_path / "environment.cfg").write_text(environment)
    vendor = GenericVendor(tmp_path, None, environment_file)
    with patch.object(BMC, "run"):
        vendor.prepare()
    assert type(vendor.get_bmc()) is expected_bmc
