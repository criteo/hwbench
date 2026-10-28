"""Intel vendor-specific implementation"""

from __future__ import annotations

import functools
import pathlib
import re

from hwbench.bench.monitoring_structs import (
    FansContext,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerConsumptionContext,
    Temperature,
    ThermalContext,
)
from hwbench.environment.vendors.bmc import BMC

# The sensors of the power of the system fans of Avenue City, one per fan board, like "System Fans SE 12V Output Power"
FANS_POWER_SENSOR = re.compile(r"System Fans .+ Output Power")


class IntelBMC(BMC):
    """Intel-specific BMC implementation for Avenue City and other Intel platforms"""

    def __init__(self, out_dir: pathlib.Path, vendor):
        super().__init__(out_dir, vendor)
        self.is_avenue_city = None  # None = not checked yet, True/False after check

    def _check_avenue_city(self):
        """Check if this is Avenue City platform (lazy detection)"""
        if self.is_avenue_city is not None:
            return self.is_avenue_city

        try:
            chassis_list = self._get_chassis()
            for chassis_url in chassis_list:
                if "AVC_Baseboard" in chassis_url:
                    self.is_avenue_city = True
                    print("Detected Intel Avenue City platform")
                    return True
        except Exception as e:
            print(f"WARNING: Could not check for Avenue City platform: {e}")

        self.is_avenue_city = False
        return False

    def detect(self):
        """Detect Intel BMC and platform type"""
        super().detect()
        # Trigger Avenue City detection
        self._check_avenue_city()

    @functools.cache
    def _get_chassis_thermals(self) -> dict[str, str]:
        """Override to handle Intel Avenue City's ThermalSubsystem endpoint"""
        if not self._check_avenue_city():
            # Use standard thermal endpoint for non-Avenue City Intel platforms
            return super()._get_chassis_thermals()

        # For Avenue City, use ThermalSubsystem endpoint
        thermals = {}
        for chassis_url in self._get_chassis():
            chassis = self.get_redfish_url(chassis_url)
            chassis_name = chassis_url.rstrip("/").split("/")[-1]

            # Try ThermalSubsystem endpoint first (Avenue City)
            thermal_subsystem = chassis.get("ThermalSubsystem")
            if thermal_subsystem and "@odata.id" in thermal_subsystem:
                thermal_subsystem_url = thermal_subsystem["@odata.id"]

                # Get the ThermalSubsystem object to check for Sensors collection
                thermal_subsystem_data = self.get_redfish_url(thermal_subsystem_url)

                # Look for temperature-related endpoints
                sensor_url = None

                # Check for Sensors collection in ThermalSubsystem
                if thermal_subsystem_data and "Sensors" in thermal_subsystem_data:
                    sensors_ref = thermal_subsystem_data["Sensors"]
                    if isinstance(sensors_ref, dict) and "@odata.id" in sensors_ref:
                        sensor_url = sensors_ref["@odata.id"]

                # Check for ThermalMetrics (common in Redfish 2020+)
                if not sensor_url and thermal_subsystem_data and "ThermalMetrics" in thermal_subsystem_data:
                    metrics_ref = thermal_subsystem_data["ThermalMetrics"]
                    if isinstance(metrics_ref, dict) and "@odata.id" in metrics_ref:
                        sensor_url = metrics_ref["@odata.id"]

                # Check for TemperatureSensors (some implementations)
                if not sensor_url and thermal_subsystem_data and "TemperatureSensors" in thermal_subsystem_data:
                    temp_ref = thermal_subsystem_data["TemperatureSensors"]
                    if isinstance(temp_ref, dict) and "@odata.id" in temp_ref:
                        sensor_url = temp_ref["@odata.id"]

                if sensor_url:
                    thermals[chassis_name] = sensor_url
                else:
                    # No specific sensors endpoint found in ThermalSubsystem
                    # Check if ThermalSubsystem itself has embedded sensor arrays (Sensors or Temperatures, not Fans)
                    if thermal_subsystem_data and any(k in thermal_subsystem_data for k in ["Sensors", "Temperatures"]):
                        thermals[chassis_name] = thermal_subsystem_url

            # Check for Sensors collection directly on Chassis (Avenue City pattern)
            if chassis_name not in thermals and "Sensors" in chassis:
                sensors_ref = chassis["Sensors"]
                if isinstance(sensors_ref, dict) and "@odata.id" in sensors_ref:
                    sensor_url = sensors_ref["@odata.id"]
                    thermals[chassis_name] = sensor_url

            # Fallback to standard Thermal endpoint if nothing found yet
            if chassis_name not in thermals:
                thermal_url = self._chassis_item_url(chassis, "Thermal")
                if thermal_url:
                    thermals[chassis_name] = thermal_url

        return thermals

    def read_thermals(self, thermals: ThermalContext) -> ThermalContext:
        """Override to handle Intel Avenue City's thermal data structure"""
        if not self._check_avenue_city():
            # Use standard thermal reading for non-Avenue City platforms
            return super().read_thermals(thermals)

        # For Avenue City, read from ThermalSubsystem
        chassis_thermals = self._get_chassis_thermals()
        temperature_sensors = self._get_temperature_sensors()

        for chassis, thermal_url in chassis_thermals.items():
            prefix = ""
            if len(chassis_thermals) > 1:
                prefix = chassis + "-"

            # A Sensors collection: only its temperature sensors hwbench reports are read
            if chassis in temperature_sensors:
                collection_url, sensor_urls = temperature_sensors[chassis]
                for _, sensor_data in self._member_bodies(collection_url, sensor_urls):
                    self._process_avenue_city_sensor(sensor_data, thermals, prefix)
                continue

            thermal_data = self.get_redfish_url(thermal_url)
            # A BMC not answering for this chassis, its sensors are read again at the next iteration
            if not thermal_data:
                continue

            # Check if this is ThermalSubsystem format (has Sensors array)
            if "Sensors" in thermal_data:
                sensors = thermal_data.get("Sensors", [])
                # Avenue City format: ThermalSubsystem with Sensors
                for sensor in sensors:
                    # Process sensor directly (they're complete objects, not references)
                    self._process_avenue_city_sensor(sensor, thermals, prefix)

            # Also check for standard Temperatures array (fallback)
            elif "Temperatures" in thermal_data:
                temps = thermal_data.get("Temperatures", [])
                for t in temps:
                    if t.get("ReadingCelsius") is None or t["ReadingCelsius"] <= 0:
                        continue
                    name = prefix + t["Name"].split("Temp")[0].strip()

                    self.add_monitoring_value(
                        thermals,
                        t.get("PhysicalContext", "UnknownPhysicalContext"),
                        Temperature(name),
                        t["Name"],
                        t["ReadingCelsius"],
                    )
            # Unknown format - silently skip (don't spam console during monitoring loop)

        return thermals

    @functools.cache
    def _get_temperature_sensors(self) -> dict[str, tuple[str, set[str]]]:
        """Auto-detect the temperature sensors of the Sensors collections of the chassis.

        Returns, for each chassis exposing one, the url of its Sensors collection and the urls
        of the temperature sensors _temperature_context() classifies, analyzed from the sensors
        read once by _get_sensors(): reading back only those spares the requests of the others,
        like the individual DIMMs, on every monitoring iteration of a BMC without '$expand'. A
        sensor the BMC did not answer for is kept, to be classified when it answers.
        """
        sensors: dict[str, tuple[str, set[str]]] = {}
        for chassis, collection_url in self._get_chassis_thermals().items():
            collection = self._get_sensors().get(collection_url)
            if collection is None:
                continue
            sensors[chassis] = (
                collection_url,
                {
                    url
                    for url, sensor in collection.items()
                    # Filter to only temperature sensors by URL pattern
                    if "temperature_" in url.lower() and (sensor is None or self._temperature_context(sensor))
                },
            )
        return sensors

    def _process_avenue_city_sensor(self, sensor_data: dict, thermals: ThermalContext, prefix: str):
        """Add the reading of an Avenue City temperature sensor, classified by _temperature_context()."""
        reading = sensor_data.get("Reading")
        name = sensor_data.get("Name", "Unknown")

        # Skip invalid readings
        if reading is None or reading <= 0:
            return

        physical_context = self._temperature_context(sensor_data)
        # If sensor doesn't match any enabled category, skip it
        if physical_context is None:
            return

        # Clean up sensor name - remove temperature-related suffixes only at the end
        clean_name = name
        for suffix in [" Temperature", " Temp"]:
            if clean_name.endswith(suffix):
                clean_name = clean_name[: -len(suffix)]
                break
        clean_name = prefix + clean_name.strip()

        self.add_monitoring_value(
            thermals,
            physical_context,
            Temperature(clean_name),
            name,
            reading,
        )

    @staticmethod
    def _temperature_context(sensor_data: dict) -> str | None:
        """Return the physical context of an Avenue City temperature sensor, None for one hwbench skips.

        Categorizes sensors into:
        - Intake: Inlet temperature sensors
        - Exhaust: Outlet/exhaust temperature sensors
        - CPU: CPU die and DTS temperature sensors
        - Memory: DIMM/Memory temperature sensors
        - VoltageRegulator: the CPU voltage regulators, like "CPU1 VCCIN Temperature"
        - PowerSupply: the power supplies, like "PSU1 Temperature"
        - SystemBoard and Backplane: the other sensors the BMC reports in these physical contexts,
          like the board, BMC, front panel and drive backplane ones
        The individual DIMM sensors are skipped, the DIMM banks summing them up.

        The classification only depends on the name and the physical context of the sensor, not on
        its reading: it is done once, when detecting the sensors.
        """
        name = sensor_data.get("Name", "Unknown")
        reading_type = sensor_data.get("ReadingType", "")

        # Only process temperature readings
        if reading_type and reading_type != "Temperature":
            return None

        # Determine physical context from sensor name
        physical_context = "UnknownPhysicalContext"
        name_upper = name.upper()

        # === ENABLED SENSORS (uncomment to add more) ===

        # Intake/Inlet temperatures (air entering chassis)
        if "INLET" in name_upper or "INTAKE" in name_upper:
            physical_context = "Intake"

        # Exhaust temperatures (air leaving chassis), like the "Exit Air Temp" of the R4000 chassis
        elif "EXIT" in name_upper or "OUTLET" in name_upper or "EXHAUST" in name_upper:
            physical_context = "Exhaust"

        # CPU die and DTS (digital thermal sensor) temperatures (processor cores)
        elif ("CPU" in name_upper and "DIE" in name_upper) or "PROCESSOR" in name_upper or name_upper.startswith("DTS"):
            physical_context = "CPU"

        # Memory Bank temperatures (aggregate for left/right DIMM banks)
        # Matches: "Left DIMM Bank", "Right DIMM Bank", "temperature_Left_DIMM_Bank_Temp"
        # but NOT: "CPU0 DIMM", "DIMM A0", etc.
        elif "BANK" in name_upper and ("DIMM" in name_upper or "MEMORY" in name_upper or "MEM" in name_upper):
            physical_context = "Memory"

        # CPU voltage regulators, which the BMC reports in the CPU physical context, like the individual DIMMs
        elif sensor_data.get("PhysicalContext") == "CPU" and "DIMM" not in name_upper:
            physical_context = "VoltageRegulator"

        # Power supplies, which the BMC reports in the SystemBoard physical context
        elif "PSU" in name_upper:
            physical_context = "PowerSupply"

        # The board, BMC, front panel and drive backplane temperatures
        elif sensor_data.get("PhysicalContext") in ("SystemBoard", "Backplane"):
            physical_context = sensor_data["PhysicalContext"]

        # If sensor doesn't match any enabled category, skip it
        else:
            return None

        return physical_context

    @functools.cache
    def _get_fan_sensors(self) -> dict[str, tuple[str, set[str]]]:
        """Auto-detect the fan speed sensors of the Sensors collections of the chassis.

        Returns, for each chassis exposing one, the url of its Sensors collection and the urls
        of its rotational sensors, analyzed from the sensors read once by _get_sensors(), like
        _get_temperature_sensors(): the other sensors whose url names a fan, like their PWM,
        current or voltage, are not read back. A sensor the BMC did not answer for is kept.
        """
        sensors: dict[str, tuple[str, set[str]]] = {}
        for chassis, collection_url in self._get_chassis_thermals().items():
            collection = self._get_sensors().get(collection_url)
            if collection is None:
                continue
            sensors[chassis] = (
                collection_url,
                {
                    url
                    for url, sensor in collection.items()
                    # Filter to only fan sensors by URL pattern
                    if "fan" in url.lower() and (sensor is None or self._is_fan_speed(sensor))
                },
            )
        return sensors

    @staticmethod
    def _is_fan_speed(sensor_data: dict) -> bool:
        """Return whether a sensor is a fan/rotational one."""
        reading_type = sensor_data.get("ReadingType", "")
        return not reading_type or reading_type.lower() == "rotational"

    @staticmethod
    def _add_fan(fans: FansContext, fan: dict):
        name = fan.get("Name", "Unknown Fan")
        reading = fan.get("Reading")
        unit = fan.get("ReadingUnits", "RPM")

        if reading is not None and reading > 0:
            if name not in fans.Fan:
                fans.Fan[name] = MonitorMetric(name, unit)
            fans.Fan[name].add(reading)

    def read_fans(self, fans: FansContext) -> FansContext:
        """Override to handle Intel Avenue City's fan data"""
        if not self._check_avenue_city():
            return super().read_fans(fans)

        fan_sensors = self._get_fan_sensors()
        for chassis_name, sensor_url in self._get_chassis_thermals().items():
            # A Sensors collection: only its fan speed sensors are read
            if chassis_name in fan_sensors:
                collection_url, sensor_urls = fan_sensors[chassis_name]
                for _, sensor_data in self._member_bodies(collection_url, sensor_urls):
                    # A sensor not answering when detected is classified now
                    if self._is_fan_speed(sensor_data):
                        self._add_fan(fans, sensor_data)
                continue

            # Check for embedded Fans array (fallback), empty when the BMC does not answer
            sensor_collection = self.get_redfish_url(sensor_url) or {}
            for f in sensor_collection.get("Fans", []):
                self._add_fan(fans, f)

        return fans

    def get_power(self):
        """Override to handle Avenue City's multiple chassis

        Avenue City has multiple chassis (AVC_Baseboard, AVC_2UDIMM_Baseboard).
        We want the main baseboard (AVC_Baseboard) for power metrics.
        """
        if not self._check_avenue_city():
            return super().get_power()

        # The Power urls of all chassis, only the one used being read
        powers = self._get_chassis_powers()

        # For Avenue City, prefer AVC_Baseboard which has the power data, fallback to first available
        url = powers.get("AVC_Baseboard") or next(iter(powers.values()), "")
        if not url:
            return {}
        # Empty when the BMC does not answer
        return self.get_redfish_url(url) or {}

    def read_oob_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Override to prevent duplicate power entries.

        Intel Avenue City provides detailed power breakdown which is handled
        in read_power_consumption() with cleaned names (Server, CPU, Memory).
        We skip the parent's read_oob_power_consumption() to avoid duplicates
        with raw names (System Power Control, Processors Power Control, etc.).
        """
        # Don't call parent - read_power_consumption handles it with cleaned names
        return power_consumption

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Override to handle Intel Avenue City's power data structure

        Avenue City provides detailed power breakdown in PowerControl array:
        - System Power Control: Total server power
        - Processors Power Control: Total CPU power
        - Processor0 Power Control: Individual CPU power
        - Memories Power Control: Total memory power
        - Memory0 Power Control: Individual memory power
        """
        if not self._check_avenue_city():
            return super().read_power_consumption(power_consumption)

        power_data = self.get_power()
        if not power_data:
            return power_consumption

        power_controls = power_data.get("PowerControl", [])

        for pc in power_controls:
            name = pc.get("Name", "")
            power_watts = pc.get("PowerConsumedWatts")

            if power_watts is None:
                continue

            # System/Server total power
            if "System" in name or name == "Server":
                if str(PowerCategories.SERVER) not in power_consumption.BMC:
                    power_consumption.BMC[str(PowerCategories.SERVER)] = Power("Server")
                power_consumption.BMC[str(PowerCategories.SERVER)].add(power_watts)

            # CPU power (aggregate or individual)
            elif "Processor" in name:
                # Use aggregate "Processors" if available, otherwise individual
                # Check if this is the aggregate (plural) vs individual (Processor0, Processor1, etc.)
                if "Processors" in name:
                    # This is aggregate - check it's not also an individual like "Processor01"
                    # Extract what comes after "Processor" to see if it's just "s" or a number
                    after_processor = name.split("Processor")[1] if len(name.split("Processor")) > 1 else ""
                    if after_processor.startswith("s"):  # "Processors Power Control"
                        if "CPU" not in power_consumption.CPU:
                            power_consumption.CPU["CPU"] = Power("CPU")
                        power_consumption.CPU["CPU"].add(power_watts)
                else:
                    # Individual processor: Processor0, Processor1, Processor2, etc.
                    # Extract the processor name (e.g., "Processor0" from "Processor0 Power Control")
                    cpu_name = name.split()[0]
                    if cpu_name.startswith("Processor") and any(c.isdigit() for c in cpu_name):
                        if cpu_name not in power_consumption.CPU:
                            power_consumption.CPU[cpu_name] = Power(cpu_name)
                        power_consumption.CPU[cpu_name].add(power_watts)

            # Memory power (aggregate or individual)
            elif "Memor" in name:  # Matches both "Memory" and "Memories"
                # Use aggregate "Memories" if available, otherwise individual
                # Check if this is the aggregate (plural) vs individual (Memory0, Memory1, etc.)
                if "Memories" in name:
                    # This is aggregate - check it's not also an individual like "Memory01"
                    # Extract what comes after "Memor" to see if it's "ies" or a number
                    after_memor = name.split("Memor")[1] if len(name.split("Memor")) > 1 else ""
                    if after_memor.startswith("ies"):  # "Memories Power Control"
                        if "Memory" not in power_consumption.BMC:
                            power_consumption.BMC["Memory"] = Power("Memory")
                        power_consumption.BMC["Memory"].add(power_watts)
                else:
                    # Individual memory: Memory0, Memory1, Memory2, etc.
                    # Extract the memory name (e.g., "Memory0" from "Memory0 Power Control")
                    mem_name = name.split()[0]
                    if mem_name.startswith("Memory") and any(c.isdigit() for c in mem_name):
                        if mem_name not in power_consumption.BMC:
                            power_consumption.BMC[mem_name] = Power(mem_name)
                        power_consumption.BMC[mem_name].add(power_watts)

        return self.read_fans_power(power_consumption)

    def _monitored_sensors(self) -> dict[str, set[str]]:
        """Add the temperature, fan speed and fan power sensors of Avenue City to the generic ones."""
        sensors = super()._monitored_sensors()
        if not self._check_avenue_city():
            return sensors
        for collection_url, urls in [
            *self._get_temperature_sensors().values(),
            *self._get_fan_sensors().values(),
            *self._get_fans_power_sensors().items(),
        ]:
            sensors.setdefault(collection_url, set()).update(urls)
        return sensors

    @functools.cache
    def _get_fans_power_sensors(self) -> dict[str, set[str]]:
        """Auto-detect the Chassis Sensors of the power of the system fans.

        Returns their urls grouped by the collection holding them, like _get_gpu_sensors(),
        analyzed from the sensors read once by _get_sensors().
        """
        sensors: dict[str, set[str]] = {}
        for collection_url, collection in self._get_sensors().items():
            for url, sensor in collection.items():
                if (
                    sensor
                    and sensor.get("ReadingType") == "Power"
                    and FANS_POWER_SENSOR.fullmatch(sensor.get("Name", ""))
                ):
                    sensors.setdefault(collection_url, set()).add(url)
        return sensors

    def read_fans_power(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        """Add the power of the system fans, the sum of the ones of their fan boards, like HPE reports it."""
        readings = [
            sensor["Reading"]
            for collection_url, sensor_urls in self._get_fans_power_sensors().items()
            for _, sensor in self._member_bodies(collection_url, sensor_urls)
            if sensor.get("Reading") is not None
        ]
        if readings:
            name = str(PowerCategories.FANS)
            if name not in power_consumption.BMC:
                power_consumption.BMC[name] = Power(name)
            power_consumption.BMC[name].add(sum(readings))
        return power_consumption
