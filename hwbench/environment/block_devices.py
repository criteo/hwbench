import pathlib
import re
from json import loads
from typing import Any

import pyudev

from hwbench.utils.external import External


class Block_Device:
    """Block_Device is a class that gathers block_device information"""

    def __init__(self, out_dir, udev_device):
        self.udev_device = udev_device
        self.name = udev_device.sys_name
        self.type = self.get_block_device_type()
        self.out_dir = out_dir
        self.smart_json = b"{}"

    def is_rotational(self) -> bool:
        syspath = f"/sys/block/{self.udev_device.sys_name}/queue/rotational"
        with open(syspath) as file:
            content = file.read()
        return bool(content.strip())

    def is_ata(self) -> bool:
        bus = self.udev_device.get("ID_BUS")
        return bool(bus == "ata")

    def is_nvme(self) -> bool:
        return bool(self.udev_device.parent.get("NVME_TRTYPE"))

    def get_block_device_type(self):
        if self.is_ata() and self.is_rotational():
            return "hdd"
        if not self.is_rotational():
            return "ssd"

    def get_smart(self):
        """Dump SMART information for all block devices"""
        smart_info = Smartctl(self.out_dir, self.name)
        return smart_info.dump()

    def get_sdparm(self):
        """Dump SMART information for all block devices"""
        sdparm_info = Sdparm(self.out_dir, self.name)
        return sdparm_info.dump()

    def get_udev_properties(self):
        """Dump UDEV properties all block devices"""
        dumped = {}
        attributes = self.udev_device.attributes
        for attribute in attributes.available_attributes:
            # The casting below is to avoid breaking struct to json. b"" cant be serialized has to be cast as string
            dumped[attribute] = (
                str(attributes.get(attribute))
                if type(attributes.get(attribute)) is bytes
                else attributes.get(attribute)
            )
        return dumped


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

    def list_disks(self):
        return sorted(list(self.data.keys()))

    def dump(self):
        dumped = {}
        for disk_name, device in self.data.items():
            dumped[disk_name] = {}
            dumped[disk_name]["smart"] = device.get_smart()
            dumped[disk_name]["sdparm"] = device.get_sdparm()
            dumped[disk_name]["udev_properties"] = device.get_udev_properties()
        return dumped


class Smartctl(External):
    """Dumps based on External abstract class SMART information for a device"""

    def __init__(self, out_dir: pathlib.Path, block_device_name):
        self.device_name = block_device_name
        self.cmd_name = "smartctl"
        self.out_dir = out_dir
        self.data = b""

    @property
    def name(self) -> str:
        return f"smartctl_{self.device_name}"

    def run_cmd(self) -> list[str]:
        return ["smartctl", "--json", "-x", f"/dev/{self.device_name}"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        self.data = loads(stdout)
        return self.data

    def run_cmd_version(self) -> list[str]:
        return ["smartctl", "-j", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        data = loads(stdout)
        self.version = ".".join(str(x) for x in data["smartctl"]["version"])
        return str.encode(self.version)

    def dump(self):
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

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        section_name = ""
        metric_name = ""

        if stdout:
            lines = stdout.splitlines()

            for line in lines:
                str_line = str(line)
                re_section = re.match(r"^(.*):$", str_line)
                if re_section:
                    section_name = re_section.group(1)
                    self.data[section_name] = {}
                    continue
                re_metric = re.match(r"^\s+(\w+)\s+(\d+)\s+\[cha: (\w{1}), def:\s+(\d+)\]$", str_line)
                if re_metric:
                    metric_name = re_metric.group(1)
                    # The casting below is to avoid breaking struct to json. b"" cant be serialized has to be cast as string
                    metric_value = str(re_metric.group(2)) if type(re_metric.group(2)) is bytes else re_metric.group(2)
                    metric_data = {
                        "value": metric_value,
                        "changeable": re_metric.group(3),
                        "default": re_metric.group(4),
                    }
                    self.data[section_name][metric_name] = metric_data
            return self.data
        else:
            return {}

    def run_cmd_version(self) -> list[str]:
        return ["sdparm", "--version"]

    def parse_version(self, _stdout: bytes, stderr: bytes) -> bytes:
        if stderr:
            self.version = stderr.split()[1]
        return self.version

    def dump(self):
        self.run()
        return self.data
