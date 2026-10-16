from __future__ import annotations

import functools
import os.path
import pathlib
from collections.abc import Iterator
from typing import Any

from hwbench.bench.monitoring_structs import (
    GPU_DESTINATIONS,
    FansContext,
    Frequency,
    MonitoringContexts,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerConsumptionContext,
    PowerSuppliesContext,
    Temperature,
    ThermalContext,
    UnitMetric,
    Utilization,
)
from hwbench.utils import helpers as h
from hwbench.utils.external import External

from .monitoring_device import MonitoringDevice

# Redfish PhysicalContext values denoting an accelerator, see
# https://redfish.dmtf.org/schemas/v1/PhysicalContext.json#/definitions/PhysicalContext
GPU_PHYSICAL_CONTEXTS = ("GPU", "Accelerator", "GPUSubsystem")

# Where each quantity belongs in the monitoring contexts, shared with the
# all-smi monitoring so the two report into the same places.
# Redfish ProcessorMetrics property -> quantity
PROCESSOR_METRICS: dict[str, type[UnitMetric]] = {
    "TemperatureCelsius": Temperature,
    "ConsumedPowerWatt": Power,
    "BandwidthPercent": Utilization,
    "OperatingSpeedMHz": Frequency,
}

# Prefix of the accelerator metrics read from the BMC, deliberately distinct
# from the GPU_<index> ones all-smi reports: both numberings are unrelated.
BMC_GPU_PREFIX = "BMC_GPU_"

# Redfish Sensor ReadingType -> quantity
SENSOR_READING_TYPES: dict[str, type[UnitMetric]] = {
    "Temperature": Temperature,
    "Power": Power,
    "Frequency": Frequency,
}


class BMC(MonitoringDevice, External):
    def __init__(self, out_dir: pathlib.Path, vendor):
        MonitoringDevice.__init__(self, vendor)
        External.__init__(self, out_dir)
        self.bmc = {}  # type: dict[str, str]
        self.bmc_section = None
        # Whether '$expand' proved usable on a given collection. Remembered so a
        # service that advertises it without honouring it is probed once, not on
        # every monitoring iteration.
        self.expand_works = {}  # type: dict[str, bool]

        # For testing purposes, vendor can be None
        if self.vendor:
            bmc_sections = vendor.find_monitoring_sections("BMC")
            if bmc_sections:
                self.bmc_section = bmc_sections[0]

    def run_cmd(self) -> list[str]:
        return ["ipmitool", "lan", "print"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        for row in stdout.split(b"\n"):
            if b": " in row:
                key, value = row.split(b": ", 1)
                if key.strip():
                    self.bmc[key.strip().decode("utf-8")] = value.strip().decode("utf-8")
        return self.bmc

    def run_cmd_version(self) -> list[str]:
        return ["ipmitool", "-V"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = stdout.split()[2].decode()
        return self.version

    @property
    def name(self) -> str:
        return "ipmitool-lan-print"

    def get_url(self) -> str:
        """Extract the BMC url."""
        # For testing purposes, vendor can be None
        if self.vendor:
            # If the configuration file provides and url, let's use it
            url = self.vendor.monitoring_config_file.get(self.bmc_section, "url", fallback="")
            if url:
                return url

        # If no url provided, let's use the ipmi address

        try:
            return f"https://{self.bmc['IP Address']}"
        except KeyError:
            h.fatal("Cannot detect BMC url")

    def connect_redfish(self):
        """Connect to the BMC using Redfish."""
        sections = self.vendor.find_monitoring_sections("BMC", [self.vendor.name(), "default"], max_sections=1)
        if not sections:
            h.fatal("Cannot find any valid BMC entry of the monitoring configuration file")

        bmc_username = self.vendor.monitoring_config_file.get(sections[0], "username")
        bmc_password = self.vendor.monitoring_config_file.get(sections[0], "password")
        return super().connect_redfish(bmc_username, bmc_password, self.get_url())

    def _get_members(self, url: str, log_failure=True) -> list[str]:
        """Return the item urls of a Redfish collection."""
        collection = self.get_redfish_url(url, log_failure)
        if not isinstance(collection, dict):
            return []
        return [
            member["@odata.id"]
            for member in collection.get("Members", [])
            if isinstance(member, dict) and isinstance(member.get("@odata.id"), str)
        ]

    @functools.cache
    def _supports_expand(self) -> bool:
        """Return True if the service advertises the '$expand=.' query parameter.

        'NoLinks' is the capability for '.', which expands the subordinate
        resources only; 'ExpandAll' is the broader '*'. Advertised in the service
        root, see the ExpandQuery object of the Redfish specification.
        """
        root = self.get_redfish_url("/redfish/v1", False)
        if not isinstance(root, dict):
            return False
        expand = root.get("ProtocolFeaturesSupported", {}).get("ExpandQuery", {})
        if not isinstance(expand, dict):
            return False
        return bool(expand.get("NoLinks") or expand.get("ExpandAll"))

    def _expanded_members(self, url: str) -> list[dict] | None:
        """Return the member bodies of a collection in a single request.

        '$expand' inlines every member of a collection, turning one request per
        member into one request for the whole collection. It is an optional
        feature, and it is unevenly implemented: a service may not advertise it,
        may reject the request, or may accept it and answer unexpanded. So the
        answer is validated rather than trusted, and None is returned whenever
        anything is off, meaning the caller must walk the members itself.
        """
        if not self._supports_expand() or self.expand_works.get(url) is False:
            return None

        separator = "&" if "?" in url else "?"
        collection = self.get_redfish_url(f"{url}{separator}$expand=.", False)
        members = collection.get("Members") if isinstance(collection, dict) else None
        # A member is only expanded if it carries more than its own reference. An
        # empty list proves nothing -- a service dropping the members it does not
        # want to expand answers exactly that -- so it is not taken for an
        # expansion, or the caller would read no member at all.
        expanded = (
            isinstance(members, list)
            and bool(members)
            and all(isinstance(member, dict) and set(member) > {"@odata.id"} for member in members)
        )
        self.expand_works[url] = expanded
        return members if expanded else None

    def _member_bodies(self, collection_url: str, wanted: set[str] | None = None) -> Iterator[tuple[str, dict]]:
        """Yield (url, body) of the members of a collection.

        <wanted> restricts the walk to those members, which is what re-reading a
        few known items of a large collection needs; None yields every member.
        Both go through '$expand' when the service honours it, and fall back to
        one request per member when it does not.
        """
        expanded = self._expanded_members(collection_url)
        if expanded is not None:
            for body in expanded:
                url = body.get("@odata.id", "")
                if wanted is None or url in wanted:
                    yield url, body
            return

        for url in wanted if wanted is not None else self._get_members(collection_url, False):
            body = self.get_redfish_url(url, False)
            if isinstance(body, dict):
                yield url, body

    @functools.cache
    def _get_chassis(self) -> list[str]:
        # List all available Chassis item URLs
        return self._get_members("/redfish/v1/Chassis")

    @functools.cache
    def _get_systems(self) -> list[str]:
        # List all available ComputerSystem item URLs
        return self._get_members("/redfish/v1/Systems", False)

    def _collection_items(self, parents: list[str], item: str) -> Iterator[tuple[str, str, dict]]:
        """Walk the <item> collection of each parent resource.

        Yields (collection url, item url, item body); the collection url lets a
        caller re-read those items later in a single expanded request.
        """
        for parent_url in parents:
            parent = self.get_redfish_url(parent_url, False)
            collection_url = self._chassis_item_url(parent, item)
            if not collection_url:
                continue
            for url, body in self._member_bodies(collection_url):
                yield collection_url, url, body

    def _chassis_item_url(self, chassis, name: str) -> str:
        if isinstance(chassis, dict) and name in chassis:
            item = chassis[name]
            if isinstance(item, dict) and "@odata.id" in item and isinstance(item["@odata.id"], str):
                return item["@odata.id"]
        return ""

    @functools.cache
    def _get_chassis_thermals(self) -> dict[str, str]:
        # Auto-detect all "Chassis" Thermal URIs
        thermals = {}
        for chassis_url in self._get_chassis():
            chassis = self.get_redfish_url(chassis_url)
            chassis_name = os.path.basename(chassis_url.rstrip("/"))
            url = self._chassis_item_url(chassis, "Thermal")
            if url:
                thermals[chassis_name] = url
        return thermals

    @functools.cache
    def _get_chassis_powers(self) -> dict[str, str]:
        # Auto-detect all "Chassis" Power URIs
        powers = {}
        for chassis_url in self._get_chassis():
            chassis = self.get_redfish_url(chassis_url)
            chassis_name = os.path.basename(chassis_url.rstrip("/"))
            url = self._chassis_item_url(chassis, "Power")
            if url:
                powers[chassis_name] = url
        return powers

    def _get_thermals(self) -> dict[str, dict[str, Any]]:
        thermals = {}
        for chassis, thermal_url in self._get_chassis_thermals().items():
            thermals[chassis] = self.get_redfish_url(thermal_url)
        return thermals

    def get_thermal(self) -> dict:
        th = self._get_thermals()
        if len(th) == 1:
            return next(iter(th.values()))  # return only element
        return {}  # return nothing if there are more than 1 elements

    def read_thermals(self, thermals: ThermalContext) -> ThermalContext:
        """Return thermals from server"""
        th = self._get_thermals()
        for chassis, thermal in th.items():
            prefix = ""
            if len(th) > 1:
                prefix = chassis + "-"
            for t in thermal.get("Temperatures", []):
                if t["ReadingCelsius"] is None or t["ReadingCelsius"] <= 0:
                    continue
                name = prefix + t["Name"].split("Temp")[0].strip()

                super().add_monitoring_value(
                    thermals,
                    t.get("PhysicalContext", "UnknownPhysicalContext"),
                    Temperature(name),
                    t["Name"],
                    t["ReadingCelsius"],
                )
        return thermals

    def read_fans(self, fans: FansContext) -> FansContext:
        """Return fans from server"""
        # Generic for now, could be overridden by vendors
        for f in self.get_thermal().get("Fans", []):
            name = f["Name"]
            if name not in fans.Fan:
                fans.Fan[name] = MonitorMetric(f["Name"], f["ReadingUnits"])
            fans.Fan[name].add(f["Reading"])
        return fans

    def _get_powers(self) -> dict[str, dict]:
        powers = {}
        for chassis, thermal_url in self._get_chassis_powers().items():
            powers[chassis] = self.get_redfish_url(thermal_url)
        return powers

    def get_power(self):
        """Return the power metrics."""
        th = self._get_powers()
        if len(th) == 1:
            return next(iter(th.values()))  # return only element
        return {}  # return nothing if there are more than 1 elements

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Return power consumption from server"""
        # Generic for now, could be overridden by vendors
        if power_consumption.BMC.get(str(PowerCategories.SERVER), None) is None:
            power_consumption.BMC[str(PowerCategories.SERVER)] = Power("Server")
        power = self.get_power().get("PowerControl", [{"PowerConsumedWatts": None}])[0].get("PowerConsumedWatts", None)
        if power:
            power_consumption.BMC[str(PowerCategories.SERVER)].add(power)
        return power_consumption

    def read_power_supplies(self, power_supplies: PowerSuppliesContext) -> PowerSuppliesContext:
        """Return power supplies power from server"""
        # Generic for now, could be overridden by vendors
        for psu in self.get_power().get("PowerSupplies", []):
            psu_name = psu["Name"].split()[0]
            if psu["Name"] not in power_supplies.BMC:
                power_supplies.BMC[psu["Name"]] = Power(psu_name)
            power_supplies.BMC[psu["Name"]].add(psu["PowerInputWatts"])
        return power_supplies

    @functools.cache
    def _get_gpu_processors(self) -> dict[str, str]:
        """Auto-detect the accelerators exposed as Processors.

        Returns the ProcessorMetrics url of each GPU, keyed by its Redfish id.
        Note that Redfish ids do not have to match the CUDA numbering.
        """
        gpus = {}
        for _, url, processor in self._collection_items(self._get_systems(), "Processors"):
            if processor.get("ProcessorType") != "GPU":
                continue
            # 'Metrics' is the current name, 'ProcessorMetrics' the older one.
            metrics_url = self._chassis_item_url(processor, "Metrics") or self._chassis_item_url(
                processor, "ProcessorMetrics"
            )
            if metrics_url:
                gpus[str(processor.get("Id", os.path.basename(url.rstrip("/"))))] = metrics_url
        return gpus

    @functools.cache
    def _get_gpu_sensors(self) -> dict[str, set[str]]:
        """Auto-detect the Chassis Sensors reported in a GPU physical context.

        Returns the GPU sensor urls grouped by the collection holding them, so
        that reading them back costs one request per collection when the service
        supports '$expand'.

        Only consulted when no accelerator was found as a Processor: without
        expansion this walk GETs every sensor of every chassis to read its
        PhysicalContext, which is by far the most expensive detection hwbench
        does, and a BMC exposing ProcessorMetrics already describes the same GPUs
        more precisely.
        """
        if self._get_gpu_processors():
            return {}
        sensors: dict[str, set[str]] = {}
        for collection_url, url, sensor in self._collection_items(self._get_chassis(), "Sensors"):
            if sensor.get("PhysicalContext") in GPU_PHYSICAL_CONTEXTS:
                # A set: _member_bodies() tests every member of the collection
                # against it on every monitoring iteration.
                sensors.setdefault(collection_url, set()).add(url)
        return sensors

    def read_metrics(self, contexts: MonitoringContexts) -> MonitoringContexts:
        """Read every metric the monitoring collects from the BMC."""
        self.read_thermals(contexts.Thermal)
        self.read_fans(contexts.Fans)
        self.read_power_consumption(contexts.PowerConsumption)
        self.read_power_supplies(contexts.PowerSupplies)
        # A no-op on a BMC exposing no accelerator: both collections it walks are
        # cached and empty there.
        self.read_gpus(contexts)
        return contexts

    def read_gpus(self, contexts: MonitoringContexts) -> MonitoringContexts:
        """Return the accelerator metrics from the server.

        Only the vendor neutral DMTF resources are used: the Processors of a
        ComputerSystem whose ProcessorType is GPU, and, when the BMC exposes
        none, the Chassis Sensors reported in a GPU physical context. A BMC
        exposing neither simply reports nothing, which is why this is not fatal:
        the all-smi monitoring covers the same quantities from the host side.

        Metrics are named BMC_GPU_<redfish id> to stay distinct from the
        GPU_<index> ones all-smi reports, as both numberings are unrelated.
        """

        def record(name: str, quantity: type[UnitMetric], value) -> None:
            destination = GPU_DESTINATIONS[quantity](contexts)
            if name not in destination:
                destination[name] = quantity(name)
            destination[name].add(float(value))

        for gpu_id, metrics_url in self._get_gpu_processors().items():
            metrics = self.get_redfish_url(metrics_url, False)
            if not isinstance(metrics, dict):
                continue
            name = f"{BMC_GPU_PREFIX}{gpu_id}"
            for key, quantity in PROCESSOR_METRICS.items():
                if metrics.get(key) is not None:
                    record(name, quantity, metrics[key])

        for collection_url, sensor_urls in self._get_gpu_sensors().items():
            for sensor_url, sensor in self._member_bodies(collection_url, sensor_urls):
                # Voltage, Current, Rotational, ... have nothing to be correlated
                # with today: ignore them rather than reporting a unitless value.
                reading_type = SENSOR_READING_TYPES.get(sensor.get("ReadingType", ""))
                if reading_type is None or sensor.get("Reading") is None:
                    continue
                sensor_name = sensor.get("Name", os.path.basename(sensor_url.rstrip("/")))
                name = f"{BMC_GPU_PREFIX}{sensor_name}"
                record(name, reading_type, sensor["Reading"])

        return contexts

    def get_gpus_count(self) -> int:
        """Return the number of accelerators the BMC describes.

        Built from the same cached discovery read_gpus() walks, so it counts
        what the BMC exposes rather than what landed in the contexts, which also
        hold the components the host side monitoring registered.
        """
        sensors = {sensor for sensors in self._get_gpu_sensors().values() for sensor in sensors}
        return len(self._get_gpu_processors()) + len(sensors)

    def has_gpus(self) -> bool:
        """Return True if the BMC exposes any accelerator metric."""
        return bool(self._get_gpu_processors() or self._get_gpu_sensors())

    def detect(self):
        """Detect monitoring device"""
        bmc_info = self.get_redfish_url("/redfish/v1/Managers/")
        members = bmc_info.get("Members")
        if not members:
            h.fatal("BMC: No member detected in 'Managers' endpoint")
        bmc_info = self.get_redfish_url(members[0]["@odata.id"])
        self.firmware_version = bmc_info.get("FirmwareVersion")
        self.model = bmc_info.get("Model")
