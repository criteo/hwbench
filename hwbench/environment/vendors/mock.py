from ...bench.monitoring_structs import (
    FanContext,
    MonitorMetric,
    Power,
    PowerCategories,
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
        name = "CPU1"
        super().add_monitoring_value(
            thermals, ThermalContext.CPU, Temperature(name), name, 40
        )
        return thermals

    def read_fans(
        self, fans: dict[str, dict[str, MonitorMetric]] = {}
    ) -> dict[str, dict[str, MonitorMetric]]:
        # Let's add a faked fans metric
        name = "Fan1"
        super().add_monitoring_value(
            fans, FanContext.FAN, MonitorMetric(name, "RPM"), name, 40
        )
        return fans

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power metric
        name = str(PowerCategories.CHASSIS)
        super().add_monitoring_value(
            power_consumption, PowerContext.BMC, Power(name), name, 125.0
        )
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power supplies
        status = "PS1 status"
        name = "PS1"
        super().add_monitoring_value(
            power_supplies, PowerContext.BMC, Power(name), status, 125
        )
        return power_supplies

    def connect_redfish(self):
        pass


class MockVendor(Vendor):
    def __init__(self, out_dir, dmi, monitoring_config_filename=None):
        self.out_dir = out_dir
        self.dmi = dmi
        self.monitoring_config_filename = monitoring_config_filename
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
