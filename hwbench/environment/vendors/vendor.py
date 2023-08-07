from abc import ABC, abstractmethod


class Vendor(ABC):
    def __init__(self, out_dir, dmi):
        self.out_dir = out_dir
        self.dmi = dmi

    @abstractmethod
    def detect(self) -> bool:
        return False

    @abstractmethod
    def save_bios_config(self):
        pass

    @abstractmethod
    def save_bmc_config(self):
        pass
