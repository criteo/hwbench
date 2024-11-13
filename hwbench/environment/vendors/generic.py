from .vendor import Vendor, BMC


class GenericVendor(Vendor):
    def __init__(
        self,
        out_dir,
        dmi,
        monitoring_config_filename,
    ):
        super().__init__(out_dir, dmi, monitoring_config_filename)
        self.bmc = BMC(self.out_dir, self)

    def detect(self) -> bool:
        return True

    def save_bios_config(self):
        print("Warning: using Generic BIOS vendor")
        # TODO: in the future, dump available BIOS config via redfish
        # in /redfish/v1/Systems/{system}/Bios
        self.out_dir.joinpath("generic-bios-config").write_text("")

    def save_bmc_config(self):
        # TODO: in the future, dump available BMC config via redfish
        # in /redfish/v1/Systems/{system} and /redfish/v1/Managers/{manager}
        # different vendors also have different Oem "backup" systems
        self.out_dir.joinpath("generic-bmc-config").write_text("")

    def name(self) -> str:
        return "GenericVendor"
