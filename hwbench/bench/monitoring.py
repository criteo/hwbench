from ..environment.hardware import BaseHardware
from ..utils import helpers as h


class Monitoring:
    """A class to perform monitoring."""

    def __init__(self, out_dir, config, hardware: BaseHardware):
        self.config = config
        self.out_dir = out_dir
        self.hardware = hardware
        self.vendor = hardware.get_vendor()
        self.prepare()

    def prepare(self):
        if self.vendor.get_bmc().get_ip() == "0.0.0.0":
            h.fatal("BMC has no IP, monitoring will not be possible")

        print(
            f"Starting monitoring for {self.vendor.name()} vendor with {self.vendor.get_bmc().get_ip()}"
        )
        if self.vendor.get_bmc().get_thermal() is None:
            h.fatal("Cannot detect thermal metrics from BMC")
