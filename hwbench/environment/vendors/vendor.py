import configparser
import cachetools.func
import json
import logging
import pathlib
import redfish  # type: ignore
from abc import ABC, abstractmethod
from ...utils import helpers as h
from ...utils.external import External
from ...bench.monitoring_structs import (
    FanContext,
    Power,
    PowerContext,
    MonitorMetric,
    Temperature,
)


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

    @cachetools.func.ttl_cache(maxsize=128, ttl=1.5)
    def get_redfish_url(self, url):
        """Return the content of a Redfish url."""
        # The same url can be called several times like read_thermals() and read_fans() consuming the same redfish endpoint.
        # To avoid multiplicating identical redfish calls, a ttl cache is implemented to avoid multiple redfish calls in a row.
        # As we want to keep a possible high frequency (< 5sec) precision, let's consider the cache must live up to 1.5 seconds
        try:
            redfish = self.redfish_obj.get(url, None).dict
            # Let's ignore errors and return empty objects
            # It will be up to the caller to see there is no answer and process this
            # {'error': {'code': 'iLO.0.10.ExtendedInfo', 'message': 'See @Message.ExtendedInfo for more information.', '@Message.ExtendedInfo': [{'MessageArgs': ['/redfish/v1/Chassis/enclosurechassis/'], 'MessageId': 'Base.1.4.ResourceMissingAtURI'}]}}
            if redfish and "error" in redfish:
                logging.error(f"Parsing redfish url {url} failed : {redfish}")
                return {}
            return redfish
        except redfish.rest.v1.RetriesExhaustedError:
            return None
        except json.decoder.JSONDecodeError:
            return None

    def get_thermal(self):
        return {}

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] = {}
    ) -> dict[str, dict[str, Temperature]]:
        """Return thermals from server"""
        # To be implemented by vendors
        return {}

    def read_fans(
        self, fans: dict[str, dict[str, MonitorMetric]] = {}
    ) -> dict[str, dict[str, MonitorMetric]]:
        """Return fans from server"""
        # Generic for now, could be override by vendors
        if not fans:
            fans[str(FanContext.FAN)] = {}  # type: ignore[no-redef]
        for f in self.get_thermal().get("Fans"):
            name = f["Name"]
            if name not in fans[str(FanContext.FAN)]:
                fans[str(FanContext.FAN)][name] = MonitorMetric(
                    f["Name"], f["ReadingUnits"]
                )
            fans[str(FanContext.FAN)][name].add(f["Reading"])
        return fans

    def get_power(self):
        """Return the power metrics."""
        return {}

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power consumption from server"""
        # Generic for now, could be override by vendors
        if not power_consumption:
            power_consumption[str(PowerContext.POWER)] = {"Chassis": Power("Chassis")}  # type: ignore[no-redef]

        power_consumption[str(PowerContext.POWER)]["Chassis"].add(
            self.get_power().get("PowerControl")[0]["PowerConsumedWatts"]
        )
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        """Return power supplies power from server"""
        # Generic for now, could be override by vendors
        if not power_supplies:
            power_supplies[str(PowerContext.POWER)] = {}  # type: ignore[no-redef]
        for psu in self.get_power().get("PowerSupplies"):
            psu_name = psu["Name"].split()[0]
            if psu["Name"] not in power_supplies[str(PowerContext.POWER)]:
                power_supplies[str(PowerContext.POWER)][psu["Name"]] = Power(psu_name)
            power_supplies[str(PowerContext.POWER)][psu["Name"]].add(
                psu["PowerInputWatts"]
            )
        return power_supplies


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
