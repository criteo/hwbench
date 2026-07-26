"""Intel vendor-specific implementation"""
from __future__ import annotations

import pathlib
from typing import Any

from hwbench.bench.monitoring_structs import (
    FansContext,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerConsumptionContext,
    Temperature,
    ThermalContext,
)

from ..bmc import BMC


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
                    if thermal_subsystem_data and any(k in thermal_subsystem_data for k in ['Sensors', 'Temperatures']):
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
        th = self._get_thermals()
        
        if not th:
            return thermals
        
        for chassis, thermal_data in th.items():
            prefix = ""
            if len(th) > 1:
                prefix = chassis + "-"
            
            # Check if this is a Sensors collection (has Members array)
            if "Members" in thermal_data:
                members = thermal_data.get("Members", [])
                # Filter to only temperature sensors by URL pattern
                temp_members = [m for m in members if isinstance(m, dict) and 
                               "@odata.id" in m and "temperature_" in m["@odata.id"].lower()]
                
                # Only print debug during first fetch (when we have many members to process)
                if len(members) > 0 and prefix == "":
                    print(f"DEBUG: Found {len(members)} sensor members, filtered to {len(temp_members)} temperature sensors")
                
                # This is a collection of sensors, each Member is a reference
                for member_ref in temp_members:
                    sensor_url = member_ref["@odata.id"]
                    sensor_data = self.get_redfish_url(sensor_url)
                    if sensor_data:
                        self._process_avenue_city_sensor(sensor_data, thermals, prefix)
            
            # Check if this is ThermalSubsystem format (has Sensors array)
            elif "Sensors" in thermal_data:
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

    def _process_avenue_city_sensor(self, sensor_data: dict, thermals: ThermalContext, prefix: str):
        """Process Avenue City sensor data
        
        Categorizes sensors into:
        - Intake: Inlet temperature sensors
        - Exhaust: Outlet/exhaust temperature sensors  
        - CPU: CPU die temperature sensors
        - Memory: DIMM/Memory temperature sensors
        
        By default, only critical sensors are reported to reduce noise in results.json.
        Uncomment categories below to enable additional sensors.
        """
        reading = sensor_data.get("Reading")
        name = sensor_data.get("Name", "Unknown")
        reading_type = sensor_data.get("ReadingType", "")
        
        # Skip invalid readings or non-temperature sensors
        if reading is None or reading <= 0:
            return
        
        # Only process temperature readings
        if reading_type and reading_type != "Temperature":
            return
        
        # Determine physical context from sensor name
        physical_context = "UnknownPhysicalContext"
        name_upper = name.upper()
        
        # === ENABLED SENSORS (uncomment to add more) ===
        
        # Intake/Inlet temperatures (air entering chassis)
        if "INLET" in name_upper or "INTAKE" in name_upper:
            physical_context = "Intake"
            
        # CPU die temperatures (processor cores)
        elif ("CPU" in name_upper and "DIE" in name_upper) or "PROCESSOR" in name_upper:
            physical_context = "CPU"
            
        # Memory Bank temperatures (aggregate for left/right DIMM banks)
        # Matches: "Left DIMM Bank", "Right DIMM Bank", "temperature_Left_DIMM_Bank_Temp"
        # but NOT: "CPU0 DIMM", "DIMM A0", etc.
        elif "BANK" in name_upper and ("DIMM" in name_upper or "MEMORY" in name_upper or "MEM" in name_upper):
            physical_context = "Memory"
            
        # === DISABLED SENSORS (uncomment to enable) ===
        
        # CPU-level DIMM aggregates (e.g., "CPU0 DIMM Temp", "CPU1 DIMM Temp")
        # elif "CPU" in name_upper and "DIMM" in name_upper and "BANK" not in name_upper:
        #     physical_context = "Memory"
        
        # Individual DIMM temperatures (e.g., "DIMM A0", "DIMM B0")
        # elif "DIMM" in name_upper and "CPU" not in name_upper and "BANK" not in name_upper:
        #     physical_context = "Memory"
        
        # General memory sensors without Bank/DIMM specification
        # elif ("MEMORY" in name_upper or "MEM" in name_upper) and "CPU" not in name_upper and "DIMM" not in name_upper:
        #     physical_context = "Memory"
        
        # === DISABLED SENSORS (uncomment to enable) ===
        
        # Exhaust/Outlet temperatures (air leaving chassis)
        # elif "OUTLET" in name_upper or "EXHAUST" in name_upper:
        #     physical_context = "Exhaust"
        
        # Motherboard/baseboard temperatures
        # elif "BOARD" in name_upper or "BASEBOARD" in name_upper:
        #     physical_context = "SystemBoard"
        
        # Voltage regulator temperatures
        # elif "VR" in name_upper or "VOLTAGE" in name_upper:
        #     physical_context = "VoltageRegulator"
        
        # If sensor doesn't match any enabled category, skip it
        else:
            return
        
        # Clean up sensor name - remove temperature-related suffixes only at the end
        clean_name = name
        for suffix in [" Temperature", " Temp"]:
            if clean_name.endswith(suffix):
                clean_name = clean_name[:-len(suffix)]
                break
        clean_name = prefix + clean_name.strip()
        
        self.add_monitoring_value(
            thermals,
            physical_context,
            Temperature(clean_name),
            name,
            reading,
        )

    def read_fans(self, fans: FansContext) -> FansContext:
        """Override to handle Intel Avenue City's fan data"""
        if not self._check_avenue_city():
            return super().read_fans(fans)
        
        # For Avenue City, get chassis thermal endpoints
        chassis_thermals = self._get_chassis_thermals()
        
        for chassis_name, sensor_url in chassis_thermals.items():
            # Fetch the Sensors collection
            sensor_collection = self.get_redfish_url(sensor_url)
            
            # Check if this is a Members collection
            if "Members" in sensor_collection:
                members = sensor_collection.get("Members", [])
                
                # Filter to only fan sensors by URL pattern
                fan_members = [m for m in members if isinstance(m, dict) and 
                              "@odata.id" in m and "fan" in m["@odata.id"].lower()]
                
                # Fetch each fan sensor
                for member_ref in fan_members:
                    fan_url = member_ref["@odata.id"]
                    sensor_data = self.get_redfish_url(fan_url)
                    
                    # Verify this is a fan/rotational sensor
                    reading_type = sensor_data.get("ReadingType", "")
                    if reading_type and reading_type.lower() not in ["rotational"]:
                        continue
                    
                    name = sensor_data.get("Name", "Unknown Fan")
                    reading = sensor_data.get("Reading")
                    unit = sensor_data.get("ReadingUnits", "RPM")
                    
                    if reading is not None and reading > 0:
                        if name not in fans.Fan:
                            fans.Fan[name] = MonitorMetric(name, unit)
                        fans.Fan[name].add(reading)
            
            # Check for embedded Fans array (fallback)
            elif "Fans" in sensor_collection:
                for f in sensor_collection.get("Fans", []):
                    name = f.get("Name", "Unknown Fan")
                    reading = f.get("Reading")
                    unit = f.get("ReadingUnits", "RPM")
                    
                    if reading is not None and reading > 0:
                        if name not in fans.Fan:
                            fans.Fan[name] = MonitorMetric(name, unit)
                        fans.Fan[name].add(reading)
        
        return fans

    def get_power(self):
        """Override to handle Avenue City's multiple chassis
        
        Avenue City has multiple chassis (AVC_Baseboard, AVC_2UDIMM_Baseboard).
        We want the main baseboard (AVC_Baseboard) for power metrics.
        """
        if not self._check_avenue_city():
            return super().get_power()
        
        # Get power from all chassis
        powers = self._get_powers()
        
        # For Avenue City, prefer AVC_Baseboard which has the power data
        if "AVC_Baseboard" in powers:
            return powers["AVC_Baseboard"]
        
        # Fallback to first available
        if powers:
            return next(iter(powers.values()))
        
        return {}

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
        
        return power_consumption
