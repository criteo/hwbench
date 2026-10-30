#!/usr/bin/env python3

"""Dump the Redfish urls hwbench reads from a BMC, as test fixtures.

The output directory has the layout of hwbench/environment/tests/vendors/<vendor>/<model>/:
- redfish_tree: a python literal mapping each url read to the answer of the BMC;
- thermal, power, oem_*: the answer of each BMC getter the vendor tests patch.
The values identifying the target machine are replaced by placeholders.
"""

from __future__ import annotations

import argparse
import contextlib
import pathlib
import pprint
import re
import tempfile
from collections.abc import Iterator

from hwbench.bench.monitoring_structs import MonitoringContexts
from hwbench.environment.dmi import DmiSys
from hwbench.environment.vendors.bmc import BMC
from hwbench.environment.vendors.detect import first_matching_vendor
from hwbench.environment.vendors.monitoring_device import MonitoringDevice, redact_secrets
from hwbench.hwbench import add_environment_option, is_root
from hwbench.utils import helpers as h

# The getters patched by the vendor tests (test_vendors.py), named like their fixture file
GETTERS = re.compile(r"get_(thermal|power|oem_\w+)")

# The services of the service root telling whether hwbench can read the sensors it monitors through a
# TelemetryService report, and under which license, with their collections: True when the members of
# a collection are read too, False for a collection only listing them, like the hundreds of
# MetricDefinitions of a Dell iDRAC
SERVICES = {
    "TelemetryService": {
        "MetricReportDefinitions": True,
        "MetricReports": True,
        "Triggers": True,
        "MetricDefinitions": False,
    },
    "LicenseService": {"Licenses": True},
}

# The keys whose value identifies the target machine, by the category of its placeholder.
# A key is matched on its last dotted component, as the Dell attributes are named
# like "ServerOS.1.HostName". A value found under several categories, like a serial
# number used as hostname, gets the placeholder of the first one.
IDENTIFYING_KEYS = {
    # The Dell express service code is the service tag in base 10, the PPIN identifies a processor,
    # a SNMP engine ID ends with the service tag of a Dell, the common names of the certificates
    # of an iDRAC are its service tag or the identifier of its card, and the entitlement ID of a
    # license identifies the one bought for the machine
    "serial": re.compile(
        r"(serialnumber|servicetag|expressservicecode|protectedidentificationnumber|engineid|issuercommonname|subjectcommonname|entitlementid)$",
        re.IGNORECASE,
    ),
    "uuid": re.compile(r"uuid$", re.IGNORECASE),
    "host": re.compile(r"(hostname|servername|certcommonname|fqdn)$", re.IGNORECASE),
    "domain": re.compile(r"domainname$", re.IGNORECASE),
    "asset": re.compile(r"assettag$", re.IGNORECASE),
    "user": re.compile(r"username$", re.IGNORECASE),
    "address": re.compile(r"(address|addresses|gateway|nameservers|dns\d*)$", re.IGNORECASE),
}
# The values of an identifying key that identify nothing: a flag, like the one of the
# Dell attribute Autodiscovery.1.EnableIPChangeAnnounceFrommDNS, or a default account
NEUTRAL_VALUES = {
    "",
    "unknown",
    "n/a",
    "na",
    "none",
    "not available",
    "notavailable",
    "not specified",
    "00000000-0000-0000-0000-000000000000",
    "enabled",
    "disabled",
    "root",
    "admin",
    "administrator",
}
NEUTRAL_ADDRESSES = re.compile(r"0+\.0+\.0+\.0+|::|(00[:-]?){5}00|255\.[0-9.]+")
# A MAC address or an EUI-64, like the identifier of a NVMe namespace in an UEFI device path
HEX_ID = re.compile(
    r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}(?:[0-9A-Fa-f]{2}\1){0,2}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])"
)
# A MAC address without separators is only recognized in an UEFI device path
UEFI_MAC_ADDRESS = re.compile(r"MAC\(([0-9A-Fa-f]{12})")
IPV4_ADDRESS = re.compile(r"\d{1,3}(\.\d{1,3}){3}")
# The address of the BMC is also found in urls, like the URLString of the Dell iDRAC card.
# Only the IP addresses are replaced: the host names found in urls are public, like redfish.dmtf.org
URL_IP_ADDRESS = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:(\d{1,3}(?:\.\d{1,3}){3})|\[([0-9A-Fa-f:.]+)\])")
# An UUID identifies the machine under any key, like the SMBIOS one a Dell repeats as smbiosGUID
UUID = re.compile(
    r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])"
)
# A shorter value is only replaced where it is found, as it could be part of unrelated strings
MIN_SUBSTRING_LENGTH = 6


class Anonymizer:
    """Replace the values identifying the target machine by placeholders.

    The same value always gets the same placeholder, wherever it is found, urls included:
    the links between the resources are kept, and a value an identifying key exposes
    is also replaced in the other strings, like a hostname in an OS description.
    """

    def __init__(self):
        self.placeholders: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.hexids: dict[str, int] = {}
        self.uuids: dict[str, int] = {}
        self.found: dict[str, list[str]] = {category: [] for category in [*IDENTIFYING_KEYS, "hexid"]}
        self.substrings: re.Pattern | None = None

    def placeholder(self, category: str, value: str):
        if category == "address":
            category = self.address_category(value)
        if category == "host" and "." in value:
            # The host and its domain can also be found apart: the fqdn is replaced through them
            host, domain = value.split(".", 1)
            self.placeholder("host", host)
            self.placeholder("domain", domain)
        elif value not in self.placeholders:
            if category == "hexid":
                # The same address, written with or without separators, gets the same number
                normalized = re.sub("[:-]", "", value).upper()
                n = self.hexids.setdefault(normalized, len(self.hexids) + 1)
            elif category == "uuid":
                # The same UUID, written in upper or lower case, gets the same number
                n = self.uuids.setdefault(value.lower(), len(self.uuids) + 1)
            else:
                n = self.counters[category] = self.counters.get(category, 0) + 1
            self.placeholders[value] = self.format(category, value, n)

    @staticmethod
    def address_category(value: str) -> str:
        if HEX_ID.fullmatch(value):
            return "hexid"
        if IPV4_ADDRESS.fullmatch(value):
            return "ipv4"
        if "@" in value:
            return "email"
        if ":" in value:
            return "ipv6"
        return "host"

    @staticmethod
    def format(category: str, value: str, n: int) -> str:
        if category == "hexid":
            # A locally administered address, with the length, the separator and the case of the original one
            separator = value[2] if HEX_ID.fullmatch(value) else ""
            size = len(value.replace(separator, "")) if separator else len(value)
            digits = f"02{n:0{size - 2}x}"
            digits = digits.upper() if value.isupper() else digits
            return separator.join(digits[i : i + 2] for i in range(0, size, 2))
        return {
            "serial": f"SERIAL{n}",
            "uuid": f"00000000-0000-0000-0000-{n:012d}",
            "host": f"host{n}",
            "domain": f"domain{n}.example.com",
            "asset": f"ASSET{n}",
            "user": f"user{n}",
            "ipv4": f"192.0.2.{n}",
            "ipv6": f"2001:db8::{n:x}",
            "email": f"user{n}@example.com",
        }[category]

    @staticmethod
    def category(key: str | None) -> str | None:
        if key is None:
            return None
        name = key.rsplit(".", 1)[-1]
        for category, pattern in IDENTIFYING_KEYS.items():
            if pattern.search(name):
                return category
        return None

    def collect(self, obj, key: str | None = None):
        """Collect every identifying value of <obj>."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                self.collect(v, k)
        elif isinstance(obj, list):
            for v in obj:
                self.collect(v, key)
        elif isinstance(obj, str):
            category = self.category(key)
            if category and obj.lower() not in NEUTRAL_VALUES and not NEUTRAL_ADDRESSES.fullmatch(obj):
                self.found[category].append(obj)
            hexids = [match.group(0) for match in HEX_ID.finditer(obj)]
            hexids += [match.group(1) for match in UEFI_MAC_ADDRESS.finditer(obj)]
            for match in URL_IP_ADDRESS.finditer(obj):
                address = match.group(1) or match.group(2)
                if not NEUTRAL_ADDRESSES.fullmatch(address):
                    self.found["address"].append(address)
            self.found["hexid"].extend(hexid for hexid in hexids if not NEUTRAL_ADDRESSES.fullmatch(hexid))
            uuids = [match.group(0) for match in UUID.finditer(obj)]
            self.found["uuid"].extend(uuid for uuid in uuids if uuid not in NEUTRAL_VALUES)

    def compile(self):
        """Give a placeholder to the values collected, and prepare their replacement."""
        for category, values in self.found.items():
            for value in values:
                self.placeholder(category, value)
        # The longest values first, so a value containing another one is replaced as a whole
        values = sorted((v for v in self.placeholders if len(v) >= MIN_SUBSTRING_LENGTH), key=len, reverse=True)
        self.substrings = re.compile("|".join(map(re.escape, values))) if values else None

    def replace(self, obj, key: str | None = None):
        """Return <obj> with every identifying value collected replaced by its placeholder."""
        if isinstance(obj, dict):
            return {self.substitute(k): self.replace(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.replace(v, key) for v in obj]
        if isinstance(obj, str):
            if obj in self.placeholders and self.category(key):
                return self.placeholders[obj]
            return self.substitute(obj)
        return obj

    def substitute(self, text: str) -> str:
        if self.substrings is None:
            return text
        return self.substrings.sub(lambda match: self.placeholders[match.group(0)], text)


@contextlib.contextmanager
def recording(device: MonitoringDevice) -> Iterator[dict]:
    """Record every url <device> reads, with its answer, while the context is active.

    An url read again gets the recorded answer, so the fixtures agree with each other.
    """
    tree: dict = {}
    get_redfish_url = device.get_redfish_url

    def get(url, log_failure=True):
        if url not in tree:
            tree[url] = get_redfish_url(url, log_failure)
        return tree[url]

    # An instance attribute shadows the method, for the calls made by the device itself
    setattr(device, "get_redfish_url", get)
    try:
        yield tree
    finally:
        delattr(device, "get_redfish_url")


def dump_services(bmc: BMC) -> None:
    """Read the SERVICES the service root links to, with their collections, only with GET requests:
    no TelemetryService report is created."""
    root = bmc.get_redfish_url("/redfish/v1", False)
    for service, collections in SERVICES.items():
        service_url = bmc._chassis_item_url(root, service)
        if not service_url:
            continue
        body = bmc.get_redfish_url(service_url, False)
        for collection, read_members in collections.items():
            collection_url = bmc._chassis_item_url(body, collection)
            if not collection_url:
                continue
            members = bmc._get_members(collection_url, False)
            if read_members:
                for url in members:
                    bmc.get_redfish_url(url, False)


def dump_fixtures(bmc: BMC, extra_urls: list[str] | None = None) -> dict[str, object]:
    """Return the fixtures of the BMC, by file name.

    redfish_tree holds the urls read by the BMC detection, by one monitoring iteration,
    by the save of the BIOS and BMC configurations, by the getters, the SERVICES, and the
    <extra_urls>, which hwbench does not read yet.
    """
    fixtures: dict[str, object] = {}
    with recording(bmc) as tree:
        bmc.detect()
        bmc.read_metrics(MonitoringContexts())
        bmc.get_bios_config()
        bmc.get_bmc_config()
        for getter in sorted(dir(bmc)):
            if match := GETTERS.fullmatch(getter):
                fixtures[match.group(1)] = getattr(bmc, getter)()
        dump_services(bmc)
        for url in extra_urls or []:
            bmc.get_redfish_url(url)
    fixtures["redfish_tree"] = tree
    return fixtures


def anonymize(fixtures: dict[str, object]) -> tuple[dict[str, object], Anonymizer]:
    """Return the fixtures with their secrets redacted, and the values identifying the target machine replaced,
    the same way in all of them."""
    fixtures = {name: redact_secrets(fixture) for name, fixture in fixtures.items()}
    anonymizer = Anonymizer()
    for fixture in fixtures.values():
        anonymizer.collect(fixture)
    anonymizer.compile()
    return {name: anonymizer.replace(fixture) for name, fixture in fixtures.items()}, anonymizer


def format_fixture(fixture: object) -> str:
    return pprint.pformat(fixture, width=120) + "\n"


def main():
    args = parse_options()
    if not is_root():
        h.fatal(
            "redfish_dump is not running as effective uid 0: it logs in to the local iLO with ilorest on HPE servers, "
            "and reads the BMC address with ipmitool on the others."
        )
    out_dir = args.output_directory
    if out_dir.exists():
        h.fatal(f"Directory {out_dir} already exists, please give a non-existent directory.")

    with tempfile.TemporaryDirectory(prefix="hwbench-redfish-dump-") as tmp:
        tmp_dir = pathlib.Path(tmp)
        vendor = first_matching_vendor(tmp_dir, DmiSys(tmp_dir), args.environment)
        bmc = vendor.get_bmc()
        bmc.connect_redfish()
        fixtures, anonymizer = anonymize(dump_fixtures(bmc, args.url))

    out_dir.mkdir(parents=True)
    for name, fixture in fixtures.items():
        (out_dir / name).write_text(format_fixture(fixture))
    tree = fixtures["redfish_tree"]
    assert isinstance(tree, dict)
    print(f"{vendor.name()} vendor with {bmc.get_driver_name()} {bmc.get_detect_string()}")
    print(f"{', '.join(fixtures)} written to {out_dir.absolute()}")
    print(f"{len(tree)} urls, {len(anonymizer.placeholders)} values anonymized")
    root = tree.get("/redfish/v1")
    services = [service for service in SERVICES if isinstance(root, dict) and service in root]
    print(f"Services: {', '.join(services) if services else 'none'} of {', '.join(SERVICES)}")
    print("Check the files before committing them: an identifying value under an unknown key is not anonymized.")


def parse_options():
    parser = argparse.ArgumentParser(
        prog="redfish_dump",
        description="Dump the Redfish urls hwbench reads from the BMC of this server, to add it to the tests.",
        epilog="Note that redfish_dump needs to run as root, for: the local login to the iLO with ilorest on HPE servers, the BMC address read with ipmitool on the other ones when the environment file has no url.",
    )
    add_environment_option(parser, required=True)
    parser.add_argument(
        "-o",
        "--output-directory",
        help="Specify the directory to write the fixtures to, like hwbench/environment/tests/vendors/<vendor>/<model>",
        type=pathlib.Path,
        required=True,
    )
    parser.add_argument(
        "-u",
        "--url",
        help="Also record this url, like /redfish/v1/Chassis/1/Power/PowerMeter/, to explore what hwbench does not read yet. Can be repeated.",
        action="append",
        default=[],
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
