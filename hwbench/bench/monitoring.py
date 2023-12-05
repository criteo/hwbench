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
        """Preparing the monitoring"""
        # Let's be sure the monitoring is functional by
        # - checking the BMC is actually connected to the network
        # - checking the thermal monitoring works
        if self.vendor.get_bmc().get_ip() == "0.0.0.0":
            h.fatal("BMC has no IP, monitoring will not be possible")

        print(
            f"Starting monitoring for {self.vendor.name()} vendor with {self.vendor.get_bmc().get_ip()}"
        )

        def check_monitoring(func, type: str):
            metrics = func
            if not len(metrics):
                h.fatal("Cannot detect thermal metrics from BMC")

            print(
                f"Monitoring {type} metrics:"
                + ", ".join(
                    [
                        f"{len(metrics[pc])}x{pc}"
                        for pc in metrics
                        if len(metrics[pc]) > 0
                    ]
                )
            )

        check_monitoring(self.vendor.get_bmc().read_thermals(), "thermal")
        check_monitoring(self.vendor.get_bmc().read_fans(), "fans")
