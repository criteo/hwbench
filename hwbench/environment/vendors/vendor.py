import configparser
import json
import pathlib
import redfish  # type: ignore
from abc import ABC, abstractmethod
from enum import Enum
from ...utils import helpers as h
from ...utils.external import External


class MonitorMetric:
    """A class to represent temperatures"""

    def __init__(self, name: str, value: float, unit: str):
        self.name = name
        self.value = value
        self.unit = unit

    def get_name(self):
        return self.name

    def get_value(self):
        return self.value

    def get_unit(self):
        return self.unit

    def __eq__(self, compared_temperature) -> bool:
        return (
            str(self.name) == str(compared_temperature.get_name())
            and self.value == compared_temperature.get_value()
            and self.unit == compared_temperature.get_unit()
        )

    def __repr__(self) -> str:
        return self.__str__()

    def __str__(self) -> str:
        return f"{self.name}={self.value} {self.unit}"


class Temperature(MonitorMetric):
    def __init__(self, name: str, value: float):
        self.name = name
        self.value = value
        super().__init__(name, value, "Celsius")


class ThermalContext(Enum):
    INTAKE = "Intake"
    CPU = "CPU"
    MEMORY = "Memory"
    SYSTEMBOARD = "SystemBoard"
    POWERSUPPLY = "PowerSupply"

    def __str__(self) -> str:
        return str(self.value)


class BMC(External):
    def __init__(self, out_dir: pathlib.Path, vendor):
        super().__init__(out_dir)
        self.bmc = {}  # type: dict[str, str]
        self.config_file: configparser.ConfigParser
        self.redfish_obj = None
        self.vendor = vendor

    def __del__(self):
        if self.redfish_obj:
            self.redfish_obj.logout()

    def run_cmd(self) -> list[str]:
        return ["ipmitool", "lan", "print"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for row in stdout.split(b"\n"):
            if b": " in row:
                key, value = row.split(b": ", 1)
                if key.strip():
                    self.bmc[key.strip().decode("utf-8")] = value.strip().decode(
                        "utf-8"
                    )
        return self.bmc

    def run_cmd_version(self) -> list[str]:
        return ["ipmitool", "-V"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[2]
        return self.version

    @property
    def name(self) -> str:
        return "ipmitool-lan-print"

    def get_ip(self) -> str:
        """Extract the BMC IP."""
        try:
            ip = self.bmc["IP Address"]
        except KeyError:
            h.fatal("Cannot detect BMC ip")

        return ip

    def connect_redfish(self):
        """Connect to the bmc using Redfish."""
        self.config_file = configparser.ConfigParser(allow_no_value=True)
        self.config_file.read("config.cfg")
        section_name = ""
        sections = [self.vendor.name(), "default"]
        for section in sections:
            if section in self.config_file.sections():
                section_name = section
                break
        if not section_name:
            h.fatal(
                f"Cannot find any section of  {sections} in monitoring configuration file"
            )

        bmc_username = self.config_file.get(section_name, "username")
        bmc_password = self.config_file.get(section_name, "password")
        server_url = self.get_ip()
        try:
            if "https://" not in server_url:
                server_url = "https://{}".format(server_url)
            self.redfish_obj = redfish.redfish_client(
                base_url=server_url,
                username=bmc_username,
                password=bmc_password,
                default_prefix="/redfish/v1",
                timeout=10,
            )
            self.redfish_obj.login()
        except json.decoder.JSONDecodeError:
            h.fatal("JSONDecodeError on {}".format(server_url))
        except redfish.rest.v1.RetriesExhaustedError:
            h.fatal("RetriesExhaustedError on {}".format(server_url))
        except redfish.rest.v1.BadRequestError:
            h.fatal("BadRequestError on {}".format(server_url))
        except redfish.rest.v1.InvalidCredentialsError:
            h.fatal("Invalid credentials for {}".format(server_url))
        except Exception as exception:
            h.fatal(type(exception))

    def get_redfish_url(self, url):
        """Return the content of a Redfish url."""
        try:
            return self.redfish_obj.get(url, None).dict
        except redfish.rest.v1.RetriesExhaustedError:
            return None
        except json.decoder.JSONDecodeError:
            return None

    def get_thermal(self):
        return {}

    def read_thermals(self) -> dict[str, dict[str, Temperature]]:
        """Return thermals from server"""
        # To be implemented by vendors
        return {}


class Vendor(ABC):
    def __init__(self, out_dir, dmi):
        self.out_dir = out_dir
        self.dmi = dmi
        self.bmc: BMC = None

    @abstractmethod
    def detect(self) -> bool:
        return False

    @abstractmethod
    def save_bios_config(self):
        pass

    @abstractmethod
    def save_bmc_config(self):
        pass

    @abstractmethod
    def name(self) -> str:
        pass

    def prepare(self):
        """If the vendor needs some specific code to init itself."""
        if not self.bmc:
            self.bmc = BMC(self.out_dir, self)
            self.bmc.run()
        # This part will be generic called by the vendors
        self.bmc.connect_redfish()

    def get_bmc(self) -> BMC:
        """Return the BMC object"""
        return self.bmc
