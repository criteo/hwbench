from __future__ import annotations

from typing import cast

from hwbench.bench.monitoring_structs import (
    FanContext,
    MonitorMetric,
    Power,
    PowerCategories,
    PowerContext,
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

    def read_thermals(
        self, thermals: dict[str, dict[str, Temperature]] | None = None
    ) -> dict[str, dict[str, Temperature]]:
        # Let's add a faked thermal metric
        if thermals is None:
            thermals = {}
        name = "CPU1"

        super().add_monitoring_value(
            cast(dict[str, dict[str, MonitorMetric]], thermals),
            ThermalContext.CPU,
            Temperature(name),
            name,
            40,
        )
        return thermals

    def read_fans(self, fans: dict[str, dict[str, MonitorMetric]] | None = None) -> dict[str, dict[str, MonitorMetric]]:
        # Let's add a faked fans metric
        if fans is None:
            fans = {}
        name = "Fan1"
        super().add_monitoring_value(
            cast(dict[str, dict[str, MonitorMetric]], fans),
            FanContext.FAN,
            MonitorMetric(name, "RPM"),
            name,
            40,
        )
        return fans

    def read_power_consumption(
        self, power_consumption: dict[str, dict[str, Power]] | None = None
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power metric
        if power_consumption is None:
            power_consumption = {}
        name = str(PowerCategories.CHASSIS)
        super().add_monitoring_value(
            cast(dict[str, dict[str, MonitorMetric]], power_consumption),
            PowerContext.BMC,
            Power(name),
            name,
            125.0,
        )
        return power_consumption

    def read_power_supplies(
        self, power_supplies: dict[str, dict[str, Power]] | None = None
    ) -> dict[str, dict[str, Power]]:
        # Let's add a faked power supplies
        if power_supplies is None:
            power_supplies = {}
        status = "PS1 status"
        name = "PS1"
        super().add_monitoring_value(
            cast(dict[str, dict[str, MonitorMetric]], power_supplies),
            PowerContext.BMC,
            Power(name),
            status,
            125,
        )
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
