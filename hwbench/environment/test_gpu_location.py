import pathlib

from .gpu_location import locate

NVIDIA = {"Brand": "Nvidia"}
UUIDS = ["GPU-1a2b3c4d-0000-0000-0000-000000000000", "GPU-1a2b3c4d-0000-0000-0000-000000000001"]


def fake_host(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Two SXM GPUs behind a PCIe switch, the first one in a slot through its switch port."""
    nvidia = root / "proc" / "gpus"
    for uuid, address in zip(UUIDS, ["0000:1b:00.0", "0000:1c:00.0"]):
        (nvidia / address).mkdir(parents=True)
        (nvidia / address / "information").write_text(f"Model: \t\t NVIDIA B200\nGPU UUID: \t {uuid}\n")

    sys_pci = root / "sys"
    # root port -> switch upstream port -> switch downstream port -> GPU
    tree = sys_pci / "real" / "pci0000:15" / "0000:15:01.0" / "0000:16:00.0"
    for downstream, gpu in [("0000:17:00.0", "0000:1b:00.0"), ("0000:17:01.0", "0000:1c:00.0")]:
        (tree / downstream / gpu).mkdir(parents=True)
    (sys_pci / "devices").mkdir()
    for path in tree.rglob("0000:1[bc]:00.0"):
        (sys_pci / "devices" / path.name).symlink_to(path)
    # The kernel names the slot after its number, and gives the bus device it holds
    (sys_pci / "slots" / "SXM_1").mkdir(parents=True)
    (sys_pci / "slots" / "SXM_1" / "address").write_text("0000:17:00\n")
    return nvidia, sys_pci


def test_locate(tmp_path):
    nvidia, sys_pci = fake_host(tmp_path)
    gpus = {
        "0": {"uuid": UUIDS[0], "detail": NVIDIA},
        "1": {"uuid": UUIDS[1], "detail": NVIDIA},
        "2": {"uuid": "GPU-unknown", "detail": NVIDIA},
        # Only the NVIDIA accelerators are located for now
        "3": {"uuid": UUIDS[1], "detail": {"Brand": "Other"}},
    }
    locate(gpus, nvidia, sys_pci)
    assert gpus["0"] == {
        "uuid": UUIDS[0],
        "detail": NVIDIA,
        "pci_address": "0000:1b:00.0",
        "slot": "SXM_1",
        "locator": "slot SXM_1",
    }
    # Without a slot, the PCI address is the locator
    assert gpus["1"]["slot"] is None
    assert gpus["1"]["locator"] == "0000:1c:00.0"
    assert gpus["2"]["locator"] is None
    assert gpus["3"]["pci_address"] is None
    assert gpus["3"]["locator"] is None


def test_no_driver(tmp_path):
    """A host without the NVIDIA driver nor slots locates nothing, without failing."""
    gpus = {"0": {"uuid": UUIDS[0], "detail": NVIDIA}}
    locate(gpus, tmp_path / "none", tmp_path / "none")
    assert gpus["0"]["locator"] is None
