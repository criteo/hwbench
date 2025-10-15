from __future__ import annotations

import configparser
import os
from abc import ABC, abstractmethod

from hwbench.utils import helpers as h

from .bmc import BMC
from .pdu import PDU


class Vendor(ABC):
    def __init__(self, out_dir, dmi, monitoring_config_filename: str):
        self.out_dir = out_dir
        self.dmi = dmi
        self.bmc: BMC | None = None
        self.pdus: list[PDU] = []
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

    def _load_vendor(self, directory: str, vendor: str):
        """Load the vendors/<vendor_name>/check module."""
        from importlib import import_module
        from importlib.util import find_spec

        vendor_modulename = f"hwbench.environment.vendors.{directory}.{vendor}"
        if not find_spec(vendor_modulename):
            h.fatal(f"cannot_find vendor module {vendor_modulename}")

        return import_module(vendor_modulename)

    def prepare(self):
        """If the vendor needs some specific code to init itself."""
        if not self.bmc:
            self.bmc = BMC(self.out_dir, self)
            self.bmc.run()
        if not self.pdus:
            pdu_sections = self.find_monitoring_sections("PDU")
            for pdu_section in pdu_sections:
                pdu_driver_name = self.monitoring_config_file.get(pdu_section, "driver", fallback="")
                if not pdu_driver_name:
                    h.fatal("PDU configuration requires a driver.")
                # for config backwards compatibility
                if pdu_driver_name.lower() == "raritan":
                    pdu_driver_name = "generic"
                pdu_driver = self._load_vendor("pdus", pdu_driver_name.lower()).init(self, pdu_section)
                self.pdus.append(pdu_driver)

    def get_bmc(self) -> BMC:
        """Return the BMC object"""
        if self.bmc:
            return self.bmc
        else:
            h.fatal("No bmc is configured")

    def get_pdus(self) -> list[PDU]:
        """Return a list of PDUs object"""
        return self.pdus

    def find_monitoring_sections(self, section_type: str, sections_list: list | None = None, max_sections=0):
        """Return sections of section_type from the monitoring configuration file"""
        if sections_list is None:
            sections_list = []
        sections = []
        if not self.get_monitoring_config_filename():
            h.fatal("Missing monitoring configuration file, please use -m option.")

        if not os.path.isfile(self.get_monitoring_config_filename()):
            h.fatal(
                f"Monitoring configuration option ({self.get_monitoring_config_filename()}) is not a file or does not exists."
            )
        self.monitoring_config_file = configparser.ConfigParser(allow_no_value=True)
        self.monitoring_config_file.read(self.get_monitoring_config_filename())

        # If no sections list is provided, let's consider all of them
        if not len(sections_list):
            sections_list = self.monitoring_config_file.sections()

        for section in sections_list:
            if section in self.monitoring_config_file.sections():
                if self.monitoring_config_file.get(section, "type", fallback="") != section_type:
                    continue
                sections.append(section)
                if len(sections) == max_sections:
                    break

        return sections
