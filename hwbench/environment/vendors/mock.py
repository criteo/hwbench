from __future__ import annotations

from hwbench.bench.monitoring_structs import (
    FansContext,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerConsumptionContext,
    PowerSuppliesContext,
    Temperature,
    ThermalContext,
)

from .vendor import BMC, Vendor


class MockedBMC(BMC):
    def get_url(self) -> str:
        return "https://1.2.3.4"

    def detect(self):
        self.firmware_version = "1.0.0"
        self.model = "MockedBMC"

    def read_thermals(self, thermals: ThermalContext) -> ThermalContext:
        # Let's add a faked thermal metric
        name = "CPU1"

        super().add_monitoring_value(
            thermals,
            "CPU",
            Temperature(name),
            name,
            40,
        )
        return thermals

    def read_fans(self, fans: FansContext) -> FansContext:
        # Let's add a faked fans metric
        name = "Fan1"
        if name not in fans.Fan:
            fans.Fan[name] = MonitorMetric(name, "RPM")
        fans.Fan[name].add(40)
        return fans

    def read_power_consumption(self, power_consumption: PowerConsumptionContext) -> PowerConsumptionContext:
        # Let's add a faked power metric
        name = str(PowerCategories.CHASSIS)
        if name not in power_consumption.BMC:
            power_consumption.BMC[name] = Power(name)
        power_consumption.BMC[name].add(125.0)
        return power_consumption

    def read_power_supplies(self, power_supplies: PowerSuppliesContext) -> PowerSuppliesContext:
        # Let's add a faked power supplies
        status = "PS1 status"
        name = "PS1"
        if status not in power_supplies.BMC:
            power_supplies.BMC[status] = Power(name)
        power_supplies.BMC[status].add(125)
        return power_supplies

    def connect_redfish(self):
        pass


class MockVendor(Vendor):
    def __init__(
        self,
        out_dir,
        dmi,
        monitoring_config_filename="hwbench/tests/mocked_monitoring.cfg",
    ):
        super().__init__(out_dir, dmi, monitoring_config_filename)
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
