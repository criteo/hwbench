import cachetools.func
import json
import logging
import redfish  # type: ignore
from ...utils import helpers as h
from ...bench.monitoring_structs import (
    MonitorMetric,
)
from typing import Any


class MonitoringDevice:
    def __init__(self, vendor):
        self.vendor = vendor
        self.redfish_obj = None
        self.logged = False
        self.firmware_version = ""
        self.model = ""
        self.serialnumber = ""

    def __del__(self):
        if self.logged:
            try:
                self.redfish_obj.logout()
            except redfish.rest.v1.RetriesExhaustedError:
                logging.warning("Cannot logout from redfish monitoring device, ignoring.")

    def get_firmware_version(self):
        return self.firmware_version

    def get_model(self):
        return self.model

    def get_serialnumber(self):
        return self.serialnumber

    def get_url(self):
        return self.vendor.monitoring_config_file.get(self.pdu_section, "url", fallback="")

    def detect(self):
        """Detect monitoring device"""
        self.firmware_version = ""
        self.model = ""
        self.serialnumber = ""

    def get_detect_string(self):
        details = f"driver @ {self.get_url()} "
        if self.get_model():
            details += f"Model: '{self.get_model()}' "

        if self.get_firmware_version():
            details += f"FW: '{self.get_firmware_version()}' "

        if self.get_serialnumber():
            details += f"Serial: '{self.get_serialnumber()}' "
        return details.strip()

    def add_monitoring_value(
        self,
        monitoring_struct: dict[str, dict[str, MonitorMetric]],
        context: Any,
        metric: MonitorMetric,
        name: str,
        value: float,
    ) -> dict[str, dict[str, MonitorMetric]]:
        """This function add a new <value> in the monitoring data structure."""
        if str(context) not in monitoring_struct:
            monitoring_struct[str(context)] = {}
        if name not in monitoring_struct[str(context)]:
            monitoring_struct[str(context)][name] = metric
        monitoring_struct[str(context)][name].add(value)
        return monitoring_struct

    def get_driver_name(self) -> str:
        """Return the driver name"""
        return type(self).__name__

    def dump(self) -> dict[str, str]:
        """Return the dump of the drive"""
        dump = {"driver": self.get_driver_name()}
        if self.firmware_version:
            dump["firmware_version"] = self.firmware_version
        if self.model:
            dump["model"] = self.model
        if self.serialnumber:
            dump["serial_number"] = self.serialnumber
        if self.get_url():
            dump["url"] = self.get_url()
        return dump

    def connect_redfish(self, username: str, password: str, device_url: str):
        """Connect to the device using Redfish."""
        try:
            if not device_url.startswith("https://"):
                h.fatal("redfish url '{device_url}' must be an https url")
            self.redfish_obj = redfish.redfish_client(
                base_url=device_url,
                username=username,
                password=password,
                default_prefix="/redfish/v1",
                timeout=10,
            )
            self.redfish_obj.login()
            self.logged = True
        except json.decoder.JSONDecodeError:
            h.fatal("JSONDecodeError on {}".format(device_url))
        except redfish.rest.v1.RetriesExhaustedError:
            h.fatal("RetriesExhaustedError on {}".format(device_url))
        except redfish.rest.v1.BadRequestError:
            h.fatal("BadRequestError on {}".format(device_url))
        except redfish.rest.v1.InvalidCredentialsError:
            h.fatal("Invalid credentials for {}".format(device_url))
        except Exception as exception:
            h.fatal(type(exception))

    @cachetools.func.ttl_cache(maxsize=128, ttl=1.5)
    def get_redfish_url(self, url, log_failure=True):
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
                if log_failure:
                    logging.error(f"Parsing redfish url {url} failed : {redfish}")
                return {}
            return redfish
        except redfish.rest.v1.RetriesExhaustedError:
            return None
        except json.decoder.JSONDecodeError:
            return None
