from __future__ import annotations

from unittest.mock import patch

from hwbench.environment.dmi import DmiSys


def test_system_serial(tmp_path):
    """The serial of the target machine, read before the DMI is archived, without spaces at its ends; None when
    it cannot be read, or is empty."""
    (tmp_path / "product_serial").write_text("CZ2D2B0FQ4\n")
    with patch.object(DmiSys, "SYS_DMI", f"{tmp_path}/"):
        assert DmiSys.system_serial() == "CZ2D2B0FQ4"
        (tmp_path / "product_serial").write_text("  CZ2D2B0FQ4   \n")
        assert DmiSys.system_serial() == "CZ2D2B0FQ4"
        (tmp_path / "product_serial").write_text("   \n")
        assert DmiSys.system_serial() is None
    with patch.object(DmiSys, "SYS_DMI", f"{tmp_path}/missing/"):
        assert DmiSys.system_serial() is None
