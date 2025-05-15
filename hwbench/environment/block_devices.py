import pathlib
from json import loads

import pyudev

from hwbench.utils.external import External


class Block_Device:
    """Block_Device is a class that gathers block_device SMART data using smartctl"""

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
