from .vendor import Vendor


class MockVendor(Vendor):
    def detect(self) -> bool:
        return True

    def save_bios_config(self):
        print("Warning: using Mock BIOS vendor")
        self.out_dir.joinpath("mock-bios-config").write_text("")
