from .vendor import (
    Power,
    MonitorMetric,
    Temperature,
    Vendor,
    BMC,
    ThermalContext,
    FanContext,
    PowerContext,
)


class MockedBMC(BMC):
    def get_ip(self) -> str:
        return "1.2.3.4"

    def read_thermals(self, thermals=None) -> dict[str, dict[str, Temperature]]:
        # Let's add a faked thermal metric
        return {str(ThermalContext.CPU): {"CPU1": Temperature("CPU1", 40)}}

    def read_fans(self, fans=None) -> dict[str, dict[str, MonitorMetric]]:
        # Let's add a faked fans metric
        return {str(FanContext.FAN): {"Fan1": MonitorMetric("Fan1", "RPM", 40)}}

    def read_power_consumption(
        self, power_consumption=None
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power metric
        return {str(PowerContext.POWER): {"Chassis": Power("Chassis", 125.0)}}

    def read_power_supplies(self, power_supplies=None) -> dict[str, dict[str, Power]]:
        # Let's add a faked power supplies
        return {str(PowerContext.POWER): {"PS1 status": Power("PS1", 125.0)}}


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
