import pathlib
from ..vendor import Vendor, BMC
from .ilorest import Ilorest, IlorestServerclone, ILOREST


class ILO(BMC):
    def __init__(self, out_dir: pathlib.Path, vendor: Vendor, ilo: ILOREST):
        super().__init__(out_dir, vendor)
        self.ilo = ilo

    def get_ip(self) -> str:
        return self.ilo.get_ip()

    def get_thermal(self):
        return self.get_redfish_url("/redfish/v1/Chassis/1/Thermal")


class Hpe(Vendor):
    def __init__(self, out_dir, dmi):
        self.out_dir = out_dir
        self.dmi = dmi
        self.bmc: ILO = None
        self.ilo = None

    def detect(self) -> bool:
        return self.dmi.info("sys_vendor") == "HPE"

    def save_bios_config(self):
        Ilorest(self.out_dir).run()

    def save_bmc_config(self):
        IlorestServerclone(self.out_dir).run()

    def name(self) -> str:
        return "HPE"

    def prepare(self):
        """Prepare the Hpe object"""
        # Let's connect to the ilo and maintain a session with it
        if not self.bmc:
            self.ilo = ILOREST()
            self.ilo.login()
            self.bmc = ILO(self.out_dir, self, self.ilo)
        super().prepare()
