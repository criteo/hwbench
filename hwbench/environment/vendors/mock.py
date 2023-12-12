from ...bench.monitoring_structs import (
    FanContext,
    MonitorMetric,
    Power,
    PowerContext,
    Temperature,
    ThermalContext,
)
from .vendor import Vendor, BMC


class MockedBMC(BMC):
    def get_ip(self) -> str:
        return "1.2.3.4"

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] = {}
    ) -> dict[str, dict[str, Temperature]]:
        # Let's add a faked thermal metric
        thermals[str(ThermalContext.CPU)] = {"CPU1": Temperature("CPU1", 40)}
        return thermals

    def read_fans(
        self, fans: dict[str, dict[str, MonitorMetric]] = {}
    ) -> dict[str, dict[str, MonitorMetric]]:
        # Let's add a faked fans metric
        fans[str(FanContext.FAN)] = {"Fan1": MonitorMetric("Fan1", "RPM", 40)}
        return fans

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power metric
        power_consumption[str(PowerContext.POWER)] = {
            "Chassis": Power("Chassis", 125.0)
        }
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power supplies

        power_supplies[str(PowerContext.POWER)] = {"PS1 status": Power("PS1", 125.0)}
        return power_supplies


class MockVendor(Vendor):
    def __init__(self, out_dir, dmi):
        self.out_dir = out_dir
        self.dmi = dmi
        self.bmc = MockedBMC(self.out_dir, self)

    def detect(self) -> bool:
        return True

    def save_bios_config(self):
        print("Warning: using Mock BIOS vendor")
        self.out_dir.joinpath("mock-bios-config").write_text("")

    def save_bmc_config(self):
        self.out_dir.joinpath("mock-bmc-config").write_text("")

    def name(self) -> str:
        return "MockVendor"

    def prepare(self):
        pass
