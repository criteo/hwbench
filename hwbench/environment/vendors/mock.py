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
        if str(ThermalContext.CPU) not in thermals:
            thermals[str(ThermalContext.CPU)] = {}
        if name not in thermals[str(ThermalContext.CPU)]:
            thermals[str(ThermalContext.CPU)][name] = Temperature(name)

        thermals[str(ThermalContext.CPU)][name].add(40)
        return thermals

    def read_fans(
        self, fans: dict[str, dict[str, MonitorMetric]] = {}
    ) -> dict[str, dict[str, MonitorMetric]]:
        # Let's add a faked fans metric
        name = "Fan1"
        if str(FanContext.FAN) not in fans:
            fans[str(FanContext.FAN)] = {}
        if name not in fans[str(FanContext.FAN)]:
            fans[str(FanContext.FAN)][name] = MonitorMetric(name, "RPM")

        fans[str(FanContext.FAN)][name].add(40)
        return fans

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power metric
        name = str(PowerCategories.CHASSIS)
        if str(PowerContext.BMC) not in power_consumption:
            power_consumption[str(PowerContext.BMC)] = {}
        if name not in power_consumption[str(PowerContext.BMC)]:
            power_consumption[str(PowerContext.BMC)][name] = Power(
                str(PowerCategories.CHASSIS)
            )

        power_consumption[str(PowerContext.BMC)][str(PowerCategories.CHASSIS)].add(
            125.0
        )
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] = {}
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power supplies
        status = "PS1 status"
        name = "PS1"
        if str(PowerContext.BMC) not in power_supplies:
            power_supplies[str(PowerContext.BMC)] = {}
        if status not in power_supplies[str(PowerContext.BMC)]:
            power_supplies[str(PowerContext.BMC)][status] = Power(name)
        power_supplies[str(PowerContext.BMC)][status].add(125)
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
