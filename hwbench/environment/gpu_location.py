"""Where an accelerator physically sits, so a result can be traced back to a card.

all-smi identifies an accelerator by its uuid, which says nothing of where the card
is plugged: a faulty card can only be pulled out of a server once its slot is known.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

# A PCI address, domain:bus:device.function, like 0000:1b:00.0
PCI_ADDRESS = re.compile(r"\b([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7])\b", re.IGNORECASE)

# The NVIDIA driver describes each GPU it drives in a directory named after its PCI address
NVIDIA_GPUS = pathlib.Path("/proc/driver/nvidia/gpus")
NVIDIA_UUID = re.compile(r"^GPU UUID:\s*(\S+)", re.MULTILINE)

SYS_PCI = pathlib.Path("/sys/bus/pci")


def nvidia_pci_addresses(root: pathlib.Path = NVIDIA_GPUS) -> dict[str, str]:
    """Return the PCI address of every GPU of the NVIDIA driver, keyed by uuid."""
    addresses = {}
    for information in sorted(root.glob("*/information")):
        try:
            match = NVIDIA_UUID.search(information.read_text(errors="replace"))
        except OSError:
            continue
        if match:
            addresses[match.group(1)] = information.parent.name.lower()
    return addresses


def vendor(gpu: dict[str, Any]) -> str | None:
    """Return the vendor of an accelerator of the inventory, None when it is not one we know."""
    brand = str((gpu.get("detail") or {}).get("Brand") or gpu.get("name") or "")
    if brand.lower().startswith("nvidia"):
        return "nvidia"
    return None


def pci_address(gpu: dict[str, Any], nvidia: dict[str, str]) -> str | None:
    """Return the PCI address of an accelerator of the inventory, None when unknown.

    The NVIDIA backend of all-smi does not report it, the driver does. The other
    vendors are not located yet: add their branch here once they are supported.
    """
    if vendor(gpu) == "nvidia":
        return nvidia.get(gpu.get("uuid") or "")
    return None


def pci_slots(sys_pci: pathlib.Path = SYS_PCI) -> dict[str, str]:
    """Return the physical slots the kernel knows, by the domain:bus:device they hold."""
    slots = {}
    for address in sorted((sys_pci / "slots").glob("*/address")):
        try:
            slots[address.read_text().strip().lower()] = address.parent.name
        except OSError:
            continue
    return slots


def slot(address: str, slots: dict[str, str], sys_pci: pathlib.Path = SYS_PCI) -> str | None:
    """Return the physical slot of a PCI device, None when it is in none the kernel knows.

    An SXM GPU is behind a PCIe switch, so the slot can be the one of a bridge
    above it: the device path is walked from the GPU up to the root port.
    """
    try:
        path = (sys_pci / "devices" / address).resolve()
    except OSError:
        return None
    for part in reversed(path.parts):
        match = PCI_ADDRESS.fullmatch(part)
        if match and part.lower().rsplit(".", 1)[0] in slots:
            return slots[part.lower().rsplit(".", 1)[0]]
    return None


def locate(
    gpus: dict[str, dict[str, Any]], nvidia_root: pathlib.Path = NVIDIA_GPUS, sys_pci: pathlib.Path = SYS_PCI
) -> dict[str, dict[str, Any]]:
    """Add to every accelerator its PCI address, its slot and a locator.

    The locator is the physical slot when the kernel knows it, the PCI address
    otherwise: on a given chassis model, a PCI address is also a fixed position.
    """
    # The NVIDIA driver is only looked at when the host has a NVIDIA accelerator
    nvidia = nvidia_pci_addresses(nvidia_root) if any(vendor(gpu) == "nvidia" for gpu in gpus.values()) else {}
    slots = pci_slots(sys_pci)
    for gpu in gpus.values():
        address = pci_address(gpu, nvidia)
        gpu["pci_address"] = address
        gpu["slot"] = slot(address, slots, sys_pci) if address else None
        gpu["locator"] = f"slot {gpu['slot']}" if gpu["slot"] else address
    return gpus
