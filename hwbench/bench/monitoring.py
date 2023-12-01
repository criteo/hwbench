from ..environment.hardware import BaseHardware


class Monitoring:
    """A class to perform monitoring."""

    def __init__(self, out_dir, config, hardware: BaseHardware):
        self.config = config
        self.out_dir = out_dir
        self.hardware = hardware
        self.vendor = hardware.get_vendor()
        self.prepare()

    def prepare(self):
        print(f"Starting monitoring for {self.vendor.name()} vendor")
