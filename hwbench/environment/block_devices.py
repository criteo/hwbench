import pathlib
import re
from enum import Enum
from json import JSONDecodeError, loads
from typing import Any

import pyudev

from hwbench.environment.oui import OUI
from hwbench.utils import helpers as h
from hwbench.utils.external import External


class Block_Device_Type(Enum):
    HDD = "hdd"
    SSD = "ssd"
    UNKNOWN = "unknown"

    def str(self):
        return str(self.value)


class Block_Device:
    """Block_Device is a class that gathers block_device information"""

    oui: str = "000000"
    manufacturer: str = "unknown"

    def __init__(self, out_dir, udev_device):
        self.udev_device = udev_device
        self.wwn = udev_device.get("ID_WWN")
        self.name = udev_device.sys_name
        self.type = self.get_block_device_type()
        self.manufacturer = self.get_manufacturer()
        self.out_dir = out_dir
        self.smart_json = b"{}"

    def is_rotational(self) -> bool:
        syspath = f"/sys/block/{self.udev_device.sys_name}/queue/rotational"
        with open(syspath) as file:
            content = file.read()
        return content.lower() in ("yes", "true", "t", "1")

    def is_ata(self) -> bool:
        bus = self.udev_device.get("ID_BUS")
        return bool(bus == "ata")

    def is_nvme(self) -> bool:
        return bool(self.udev_device.parent.get("NVME_TRTYPE"))

    def get_block_device_type(self) -> Block_Device_Type:
        if self.is_ata() and self.is_rotational():
            return Block_Device_Type.HDD
        if not self.is_rotational():
            return Block_Device_Type.SSD
        return Block_Device_Type.UNKNOWN

    def get_smart(self) -> dict[str, Any]:
        """Dump SMART information for current block device"""
        smart_info = Smartctl(self.out_dir, self.name)
        return smart_info.dump()

    def get_sdparm(self):
        """Dump sdparm information for current block devices"""
        sdparm_info = Sdparm(self.out_dir, self.name)
        return sdparm_info.dump()

    def get_udev_properties(self) -> dict[str, Any]:
        """Dump UDEV properties for current block device"""
        dumped: dict[str, Any] = {}
        for property in self.udev_device:
            dumped[property] = self.udev_device.get(property)
        return dumped

    def get_udev_attributes(self) -> dict[str, Any]:
        """Dump UDEV attributes for current block device"""
        dumped: dict[str, Any] = {}
        attributes = self.udev_device.attributes
        for attribute in attributes.available_attributes:
            # The casting below is to avoid breaking struct to json. b"" cant be serialized has to be cast as string
            dumped[attribute] = (
                str(attributes.get(attribute))
                if type(attributes.get(attribute)) is bytes
                else attributes.get(attribute)
            )
        return dumped

    def get_manufacturer(self) -> str:
        if not self.wwn:
            return self.manufacturer

        ouidb = OUI()
        self.oui = ouidb.wwn_to_oui(self.wwn)
        self.manufacturer = ouidb.hex_to_manufacturer(self.oui)
        return self.manufacturer


class Block_Devices:
    """Block_Devices is a class that gets a list of block_devices using pyudev and holds a collection of corresponding Block_device objects"""

    udev_context = pyudev.Context()
    data: dict[str, Block_Device] = {}

    def __init__(self, out_dir: pathlib.Path):
        self.out_dir = out_dir
        self.__discover_devices()

    def __discover_devices(self):
        for device in self.udev_context.list_devices(subsystem="block", DEVTYPE="disk"):
            dname = device.get("DEVNAME")
            self.data[dname] = Block_Device(self.out_dir, device)

    def list_disks(self) -> list:
        return sorted(list(self.data.keys()))

    def dump(self) -> dict[str, dict[str, Any]]:
        dumped: dict[str, Any] = {}
        for disk_name, device in self.data.items():
            dumped[disk_name] = {}
            dumped[disk_name]["smart"] = device.get_smart()
            dumped[disk_name]["sdparm"] = device.get_sdparm()
            dumped[disk_name]["udev_properties"] = device.get_udev_properties()
            dumped[disk_name]["udev_attributes"] = device.get_udev_attributes()
            dumped[disk_name]["manufacturer"] = device.get_manufacturer()

        return dumped


class Smartctl(External):
    """Dumps based on External abstract class SMART information for a device"""

    def __init__(self, out_dir: pathlib.Path, block_device_name):
        self.device_name = block_device_name
        self.cmd_name = "smartctl"
        self.out_dir = out_dir
        self.data: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return f"smartctl_{self.device_name}"

    def run_cmd(self) -> list[str]:
        return ["smartctl", "--json", "-x", f"/dev/{self.device_name}"]

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        try:
            self.data = loads(stdout)
        except JSONDecodeError:
            h.fatal(stdout)
        return self.data

    def run_cmd_version(self) -> list[str]:
        return ["smartctl", "-j", "--version"]

    def parse_version(self, stdout: bytes, stderr: bytes) -> bytes:
        try:
            data = loads(stdout)
        except JSONDecodeError:
            h.fatal(stdout)
        self.version = ".".join(str(x) for x in data["smartctl"]["version"])
        return str.encode(self.version)

    def dump(self) -> dict[str, Any]:
        self.run()
        return self.data


class Sdparm(External):
    """Dumps based on External abstract class Sdparm tool information for a block device"""

    def __init__(self, out_dir: pathlib.Path, block_device_name):
        self.device_name = block_device_name
        self.cmd_name = "sdparm"
        self.out_dir = out_dir
        self.data: dict[str, dict[str, Any]] = {}
        self.version = b""

    @property
    def name(self) -> str:
        return f"sdparm_{self.device_name}"

    def run_cmd(self) -> list[str]:
        return ["sdparm", "--all", f"/dev/{self.device_name}"]

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, dict[str, Any]]:
        # here is a sdparm output excerpt. Look at the parsing tests for more
        # Informational exceptions control mode page:
        #  PERF          0  [cha: n, def:  0, sav:  0]
        #  EBF           0  [cha: n, def:  0, sav:  0]
        mode_page_pattern = re.compile(r"^(-?.+ mode page):")
        setting_pattern = re.compile(r"^\s+(\S+)\s+(-?\d+)\s+\[cha:\s+(\w),\s+def:\s+(-?\d+),\s+sav:\s+(-?\d+)\]")

        current_mode_page = None

        if stdout:
            for line in stdout.splitlines():
                if not line:
                    continue
                # Check for mode page header
                mode_match = mode_page_pattern.match(line.decode())
                if mode_match:
                    current_mode_page = mode_match.group(1)
                    self.data[current_mode_page] = {}
                    continue

                # Check for setting line
                setting_match = setting_pattern.match(line.decode())
                if setting_match and current_mode_page:
                    name, current, changeable, default, saved = setting_match.groups()
                    # The casting below is to avoid breaking struct to json. b"" cant be serialized has to be cast as string
                    value = str(current) if type(current) is bytes else current
                    metric_data = {
                        "default": int(default),
                        "saved": int(saved),
                        "current": value,
                        "changeable": changeable.lower() == "y",
                    }
                    self.data[current_mode_page][name] = metric_data
        return self.data

    def run_cmd_version(self) -> list[str]:
        return ["sdparm", "--version"]

    def parse_version(self, stdout: bytes, stderr: bytes) -> bytes:
        if stderr:
            self.version = stderr.split()[1]
        return self.version

    def dump(self) -> dict[str, dict[str, Any]]:
        self.run()
        return self.data
