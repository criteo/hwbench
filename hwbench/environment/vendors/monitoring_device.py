from __future__ import annotations

import dataclasses
import json
import logging
import math
import re
from collections.abc import Coroutine
from typing import Any

import cachetools.func
import redfish  # type: ignore

from hwbench.bench.monitoring_structs import MonitoringContextKeys, MonitoringContexts, MonitorMetric
from hwbench.utils import helpers as h


class DeviceError(Exception):
    """A monitoring device that cannot be used as configured: a wrong url, wrong credentials..."""


class DeviceNotReady(DeviceError):
    """A monitoring device not answering, or not giving its metrics: a later attempt may succeed."""


# The kinds of the values of the environment file, as the errors name them
VALUE_KINDS: dict[Any, str] = {int: "an integer", float: "a number"}

# The keys holding a secret, like the password hashes, the IPMI or SNMPv3 keys and the SNMP
# communities of the Dell iDRAC users. A key is matched on its last dotted component, as the
# Dell attributes are named like "Users.2.SHA256Password".
SECRET_KEYS = re.compile(r"(password|salt|key|passphrase|secret|community|communityname|token)$", re.IGNORECASE)
# A flag telling whether a secret is used, like StrongPassword in a Dell BIOS, is not one
NOT_SECRETS = {"enabled", "disabled", "true", "false", "yes", "no"}
REDACTED = "<redacted>"


def redact_secrets(obj: Any, key: str | None = None) -> Any:
    """Return obj, read from a Redfish device, with the value of every secret replaced by REDACTED.

    An empty secret is kept, to tell whether one is set."""
    if isinstance(obj, dict):
        return {k: redact_secrets(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_secrets(v, key) for v in obj]
    if (
        key is not None
        and SECRET_KEYS.search(key.rsplit(".", 1)[-1])
        and obj not in (None, "")
        and str(obj).lower() not in NOT_SECRETS
    ):
        return REDACTED
    return obj


def section_value(config, device: str, section: str | None, key: str, fallback: Any = None, convert: Any = None) -> Any:
    """The value of a key of the section of a device in the environment file: the BMC, a PDU or a CDU.

    A key absent or empty takes the fallback, or stops hwbench when there is none, as it is required.
    A value convert cannot read, like a timeout of '0.5s', stops hwbench too: both errors name the
    device, its section and the key, '<device> <section>: <key> ...'."""
    value = config.get(section, key, fallback="")
    if not value:
        if fallback is None:
            h.fatal(f"{device} {section}: {key} is required")
        return fallback
    if convert is None:
        return value
    try:
        return convert(value)
    except ValueError:
        h.fatal(f"{device} {section}: {key} must be {VALUE_KINDS.get(convert, convert.__name__)}, got {value!r}")


def check_metrics(source: str, metric_name: MonitoringContextKeys, data: Any) -> None:
    """Print the metrics of a source, DeviceNotReady when it gives none."""
    if not isinstance(data, dict):
        # Probably a dataclass
        data = dataclasses.asdict(data)

    if not len(data):
        raise DeviceNotReady(f"Cannot detect {str(metric_name)} metrics")

    print(
        f"Monitoring/{source}: {str(metric_name)} metrics: "
        + ", ".join([f"{len(data[pc])}x{pc}" for pc in data if len(data[pc]) > 0])
    )


# The section of the environment file giving the settings of all the devices, each one overriding them in its section
MONITORING_SECTION = "monitoring"
# The longest wait for the devices to answer when the monitoring starts, and the delays between two attempts, in seconds
DEFAULT_INIT_TIMEOUT = 120.0
DEFAULT_RETRY_DELAY = "5-30"


def init_timeout(config) -> float:
    """The longest wait for the devices to answer when the monitoring starts, before hwbench stops, in
    seconds: the init_timeout of [monitoring], 0 giving them a single attempt."""
    value = config.get(MONITORING_SECTION, "init_timeout", fallback="")
    if not value:
        return DEFAULT_INIT_TIMEOUT
    try:
        timeout = float(value)
    except ValueError:
        timeout = math.nan
    if not math.isfinite(timeout) or timeout < 0:
        h.fatal(f"{MONITORING_SECTION}: init_timeout must be a number of seconds, 0 or more, got {value!r}")
    return timeout


def retry_delays(config, device: str, section: str | None) -> list[int]:
    """The delays between two attempts to reach a device, in seconds, one drawn at random each time: the
    retry_delay of its section, or of [monitoring], with the range syntax of the job files, like 5-30."""
    value = config.get(section, "retry_delay", fallback="") if section else ""
    where = f"{device} {section}"
    if not value:
        value = config.get(MONITORING_SECTION, "retry_delay", fallback="") or DEFAULT_RETRY_DELAY
        where = MONITORING_SECTION
    delays = h.parse_range(value)
    if not delays or not all(isinstance(delay, int) for delay in delays):
        h.fatal(f"{where}: retry_delay must be a number of seconds, or a range of them like 5-30, got {value!r}")
    return delays


class MonitoringDevice:
    """A source of the monitoring: turbostat, all-smi, the BMC, a PDU or a CDU."""

    def __init__(self):
        self.firmware_version = ""
        self.manufacturer = ""
        self.model = ""
        self.serialnumber = ""

    def get_label(self) -> str:
        """The name of the device in the messages of the monitoring, like 'BMC' or 'PDU <section>'."""
        return self.get_driver_name()

    def get_retry_delays(self) -> list[int]:
        """The delays before trying again to initialize a device not ready, in seconds, one drawn at
        random each time: none for a source on the server itself, which would fail the same way."""
        return []

    def initialize(self, contexts: MonitoringContexts) -> Coroutine[Any, Any, None] | None:
        """Start the device when the monitoring starts, and read it once in <contexts>: DeviceNotReady
        when it gives no metric, DeviceError when it cannot be used as configured. A device built on an
        async library defines it as an async def: it runs in an event loop of the thread of the device."""
        raise NotImplementedError

    def get_firmware_version(self):
        return self.firmware_version

    def get_model(self):
        return self.model

    def get_serialnumber(self):
        return self.serialnumber

    def get_url(self):
        return ""

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
        if self.manufacturer:
            dump["manufacturer"] = self.manufacturer
        return dump


class RedfishDevice(MonitoringDevice):
    """A monitoring device read with Redfish: the BMC or a PDU."""

    def __init__(self, vendor):
        super().__init__()
        self.vendor = vendor
        self.redfish_obj = None
        self.redfish_url = ""
        self.logged = False
        # The number of Redfish requests the device did not answer in time
        self.timeouts = 0
        # The urls whose last request was not answered in time
        self.unanswered_urls: set[str] = set()

    def __del__(self):
        self.disconnect_redfish()

    def disconnect_redfish(self):
        """Close the Redfish session, if any."""
        if self.logged:
            try:
                self.redfish_obj.logout()
            except redfish.rest.v1.RetriesExhaustedError:
                logging.warning("Cannot logout from redfish monitoring device, ignoring.")
            self.redfish_obj = None
            self.logged = False

    def did_not_answer(self, url: str) -> bool:
        """Return True if the last request of <url>, cached or not, was not answered in time."""
        return url in self.unanswered_urls

    def connect_redfish(self, username: str, password: str, device_url: str):
        try:
            self._connect_redfish(username, password, device_url, redfish.AuthMethod.SESSION)
        # This is a workaround for very simple devices, like Enlogic/NVent that don't support session mode (!!!)
        except redfish.rest.v1.SessionCreationError as e:
            logging.warning(f"Redfish session authentication error for {device_url}: '{e}'; trying HTTP Basic mode.")
            try:
                self._connect_redfish(username, password, device_url, redfish.AuthMethod.BASIC)
            except redfish.rest.v1.SessionCreationError as e:
                raise DeviceError(f"Unable to authenticate with neither session nor basic mode for {device_url}: {e}")

    def _connect_redfish(self, username: str, password: str, device_url: str, auth_method: str):
        """Connect to the device using Redfish."""
        if not device_url.startswith("https://"):
            raise DeviceError(f"redfish url '{device_url}' must be an https url")
        try:
            self.redfish_url = device_url
            self.redfish_obj = redfish.redfish_client(
                base_url=device_url,
                username=username,
                password=password,
                default_prefix="/redfish/v1",
                timeout=10,
                # Retried 10 times by default, a request not answered took 2 minutes to give up, delaying
                # the monitoring loop as much: get_redfish_url() makes a single attempt per request. Not 0
                # here: python-redfish-library 3.3.4 compares the attempts made with the max_retry of the
                # client, raising RetriesExhaustedError on every request answered, the login included
                max_retry=1,
            )
            self.redfish_obj.login(auth=auth_method)
            self.logged = True
        except json.decoder.JSONDecodeError:
            raise DeviceNotReady(f"JSONDecodeError on {device_url}")
        except redfish.rest.v1.RetriesExhaustedError:
            raise DeviceNotReady(f"RetriesExhaustedError on {device_url}")
        except redfish.rest.v1.BadRequestError:
            raise DeviceError(f"BadRequestError on {device_url}")
        except redfish.rest.v1.InvalidCredentialsError:
            raise DeviceError(f"Invalid credentials for {device_url}")
        except redfish.rest.v1.SessionCreationError as e:
            raise e
        except Exception as exception:
            # A device unreachable, or rebooting, most of the time: ServerDownOrUnreachableError...
            raise DeviceNotReady(
                f"unknown exception '{type(exception)}' connecting redfish to {device_url}: {exception}"
            )

    @cachetools.func.ttl_cache(maxsize=128, ttl=1.5)
    def get_redfish_url(self, url, log_failure=True) -> dict:
        """Return the content of a Redfish url, an empty dict when there is none.

        A device not answering in time gives an empty dict too: the readings of the iteration are skipped.
        """
        # The same url can be called several times like read_thermals() and read_fans() consuming the same redfish endpoint.
        # To avoid multiplicating identical redfish calls, a ttl cache is implemented to avoid multiple redfish calls in a row.
        # As we want to keep a possible high frequency (< 5sec) precision, let's consider the cache must live up to 1.5 seconds
        try:
            if self.redfish_obj is None:
                return {}
            # A single attempt, see _connect_redfish(): a request not answered gives no response
            response = self.redfish_obj.get(url, None, max_retry=0)
            if response is None:
                raise redfish.rest.v1.RetriesExhaustedError()
            content = response.dict
            self.unanswered_urls.discard(url)
            # Let's ignore errors and return empty objects
            # It will be up to the caller to see there is no answer and process this
            # {'error':
            # {'code': 'iLO.0.10.ExtendedInfo', 'message': 'See @Message.ExtendedInfo for more information.', '@Message.ExtendedInfo':
            # [{'MessageArgs': ['/redfish/v1/Chassis/enclosurechassis/'], 'MessageId': 'Base.1.4.ResourceMissingAtURI'}]}}
            if content and "error" in content:
                if log_failure:
                    logging.error(f"Parsing redfish url {url} failed : {content}")
                return {}
            return content
        except redfish.rest.v1.RetriesExhaustedError:
            self.timeouts += 1
            self.unanswered_urls.add(url)
            logging.warning(f"Redfish {self.redfish_url}{url} did not answer in time, skipping this reading")
            return {}
        except json.decoder.JSONDecodeError:
            return {}
