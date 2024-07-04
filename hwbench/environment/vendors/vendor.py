from abc import ABC, abstractmethod
from .bmc import BMC


class Vendor(ABC):
    def __init__(self, out_dir, dmi, monitoring_config_filename):
        self.out_dir = out_dir
        self.dmi = dmi
        self.bmc: BMC = None
        self.monitoring_config_filename = monitoring_config_filename

    @abstractmethod
    def detect(self) -> bool:
        return False

    @abstractmethod
    def save_bios_config(self):
        pass

    @abstractmethod
    def save_bmc_config(self):
        pass

    @abstractmethod
    def name(self) -> str:
        pass

    def get_monitoring_config_filename(self):
        return self.monitoring_config_filename

    def prepare(self):
        """If the vendor needs some specific code to init itself."""
        if not self.bmc:
            self.bmc = BMC(self.out_dir, self)
            self.bmc.run()

    def get_bmc(self) -> BMC:
        """Return the BMC object"""
        return self.bmc
