from .vendor import Temperature, Vendor, BMC, ThermalContext


class MockedBMC(BMC):
    def get_ip(self) -> str:
        return "1.2.3.4"

    def read_thermals(self) -> dict[str, dict[str, Temperature]]:
        # Let's add a faked thermal metric
        return {str(ThermalContext.CPU): {"CPU1": Temperature("CPU1", 40)}}


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
