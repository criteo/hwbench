from __future__ import annotations

import configparser
import importlib
import os
import re
from typing import Any

from . import config_syntax
from ..bench.engine import EngineBase
from ..environment import hardware as env_hw
from ..utils import helpers as h


class Config:
    def __init__(self, jobs_file: str, hardware: env_hw.Hardware):
        self.jobs_file = jobs_file
        if not os.path.isfile(self.jobs_file):
            h.fatal(f"File '{self.jobs_file}' does not exists.")

        # Ensure default options from the configuration file
        default_parameters = {
            "runtime": "60",
            "monitor": "none",
            "stressor_range": "1",
            "stressor_range_scaling": "plus_1",
            "hosting_cpu_cores": "none",
            "hosting_cpu_cores_scaling": "iterate",
            "engine_module_parameter_base": "",
            "skip_method": "bypass",
            "sync_start": "none",
        }
        self.jobs_config = configparser.RawConfigParser(default_section="global", defaults=default_parameters)
        self.hardware = hardware
        self.jobs_config.read(self.jobs_file)

    def to_dict(self) -> dict:
        output_dict = dict()
        for section in self.jobs_config.sections():
            items = self.jobs_config.items(section)
            output_dict[section] = dict(items)
        return output_dict

    def get_sections(self) -> list[str]:
        """Return all sections of a config file."""
        return self.jobs_config.sections()

    def get_section(self, section_name) -> configparser.SectionProxy:
        """Return one section of a config file"""
        return self.jobs_config[section_name]

    def get_valid_keywords(self) -> list[str]:
        """Return the list of valid keywords."""
        return [
            "runtime",
            "monitor",
            "engine",
            "engine_module",
            "engine_module_parameter",
            "engine_module_parameter_base",
            "stressor_range",
            "stressor_range_scaling",
            "hosting_cpu_cores",
            "hosting_cpu_cores_scaling",
            "thermal_start",
            "fans_start",
            "skip_method",
            "sync_start",
        ]

    def get_directive(self, section_name, directive) -> str:
        """Return one directive of a section."""
        return self.get_section(section_name)[directive].lower()

    def get_runtime(self, section_name) -> int:
        """Return the runtime value of a section."""
        return int(self.get_directive(section_name, "runtime"))

    def get_monitor(self, section_name) -> str:
        """Return the monitor value of a section."""
        return self.get_directive(section_name, "monitor")

    def get_engine(self, section_name) -> str:
        """Return the engine value of a section."""
        return self.get_directive(section_name, "engine")

    def load_engine(self, engine_name) -> EngineBase:
        """Return the engine from <engine_name> type."""
        module = importlib.import_module("..engines.{}".format(engine_name), package="hwbench.engines")
        return module.Engine()

    def get_engine_module(self, section_name) -> str:
        """Return the engine module name of a section."""
        # If no engine_module is defined, considering the engine name
        try:
            engine_module = self.get_directive(section_name, "engine_module")
        except KeyError:
            engine_module = self.get_engine(section_name)
        return engine_module

    def get_engine_module_parameter(self, section_name) -> list[str]:
        """Return the engine module parameter name of a section."""
        # If no engine_module_parameter is defined, considering the engine_module name
        try:
            engine_module_parameter = self.get_directive(section_name, "engine_module_parameter")
        except KeyError:
            engine_module_parameter = self.get_engine_module(section_name)
        return self.parse_range(engine_module_parameter)

    def get_engine_module_parameter_base(self, section_name) -> str:
        """Return the engine module parameter base."""
        return self.get_directive(section_name, "engine_module_parameter_base")

    def get_stressor_range(self, section_name) -> list[str]:
        """Return the stressor range of a section."""
        return self.parse_range(self.get_directive(section_name, "stressor_range"))

    def get_stressor_range_scaling(self, section_name) -> str:
        """Return the stressor range scaling of a section."""
        return self.get_directive(section_name, "stressor_range_scaling")

    def get_hosting_cpu_cores(self, section_name) -> list[str]:
        """Return the hosting cpu cores of a section."""

        def get_cores_from_quadrant(quadrant):
            """Return the core list for a quadrant"""
            core_list = self.hardware.get_cpu().get_cores_in_quadrant(int(quadrant))
            if not core_list:
                h.fatal(f"Quadrant {quadrant} does not exists")
            return core_list

        def get_cores_from_domain(domain):
            """Return the core list for a particular numa domain name"""
            core_list = self.hardware.get_cpu().get_logical_cores_in_numa_domain(int(domain))
            if not core_list:
                h.fatal(f"NUMA domain {domain} does not exists")
            return core_list

        def get_physical_cores(core):
            """Return the cores list for a particular physical core"""
            if int(core) > self.hardware.get_cpu().get_physical_cores_count():
                h.fatal(f"CPU: Physical core {core} does not exists")

            core_list = self.hardware.get_cpu().get_peer_siblings(int(core))

            if not core_list:
                h.fatal(f"Unable to find sibblings for cpu core {core}")
            return core_list

        hcc = self.get_directive(section_name, "hosting_cpu_cores")

        # Let's replace 'all' special keyword if any
        all = re.findall("all", hcc)
        if all:
            hcc = hcc.replace("all", f"0-{self.hardware.get_cpu().get_logical_cores_count()-1}")

        # Let's replace helpers if any
        helpers = re.findall("simple", hcc)
        if helpers:
            for helper in helpers:
                helper_module = importlib.import_module(  # noqa: F841
                    ".config_helpers", package="hwbench.config"
                )
                hcc = hcc.replace(helper, eval(f"helper_module.{helper}")(self.hardware), 1)

        # If the hcc has some numa domains, lets expand them.
        # Let's search if there is any numa keyword
        ressources = re.findall(r"(quadrant|numa|core)([0-9-,]+)", hcc)

        if ressources:
            if self.hardware is None:
                h.fatal("Incorrect hardware init")

            for ressource_name, ressource in ressources:
                cpus = ""
                ints = []
                # reuse the same parse_range function for a consistent syntax
                for value in self.parse_range(ressource):
                    ressource_function = None
                    if ressource_name == "quadrant":
                        ressource_function = get_cores_from_quadrant
                    elif ressource_name == "numa":
                        ressource_function = get_cores_from_domain
                    else:
                        ressource_function = get_physical_cores
                    ints += ressource_function(value)

                # Let's build the list of cpu for the selected numa domains
                cpus = ",".join(str(e) for e in sorted(ints))
                # Replace only the matched domain by the list of cpus
                hcc = hcc.replace(f"{ressource_name}{ressource}", cpus, 1)

        ressources = re.findall(r"(all|simple|quadrant.*|numa.*|core.*)", hcc)
        if ressources:
            h.fatal(f"The following keywords, didn't got processed ! : {ressources}")
        return self.parse_range(hcc)

    def get_hosting_cpu_cores_scaling(self, section_name) -> str:
        """Return the hosting cpu cores scaling of a section."""
        return self.get_directive(section_name, "hosting_cpu_cores_scaling")

    def get_skip_method(self, section_name) -> str:
        """Return the skipping method of a section."""
        return self.get_directive(section_name, "skip_method")

    def get_sync_start(self, section_name) -> str:
        """Return the sync_start method of a section."""
        return self.get_directive(section_name, "sync_start")

    def is_valid_keyword(self, keyword) -> bool:
        """Return if a keyword is valid"""
        return keyword in self.get_valid_keywords()

    def validate_sections(self):
        """Validates all sections of a config file."""
        for section_name in self.get_sections():
            self.validate_section(section_name)

    def validate_section(self, section_name):
        """Validate <section_name> section of a config file."""
        for directive in self.get_section(section_name):
            if not self.is_valid_keyword(directive):
                h.fatal("job {}: invalid keyword {}".format(section_name, directive))
            # Execute the validations_<function> from config_syntax file
            # It will validate the syntax of this particular function.
            # An invalid syntax is fatal and halts the program
            validate_function = getattr(config_syntax, "validate_{}".format(directive))
            message = validate_function(self, section_name, self.get_section(section_name)[directive])
            if message:
                h.fatal(f"Job {section_name}: keyword {directive} : {message}")

    def get_config(self) -> configparser.RawConfigParser:
        """Return the configuration object."""
        return self.jobs_config

    def parse_range(self, input: str) -> list[Any]:
        """A function to parse the range syntax from a configuration directive."""
        result: list[int | str | list[int]] = []
        # FIXME: implement 'all'
        # group1 group2...
        groups_count = len(input.split(" "))

        for group in input.split(" "):
            # syntax: <x>,<y>
            current_group: list[Any] = []
            # Let's remove the [] if any
            for item in group.split(","):
                # syntax: <x>-<y>
                if "-" in item:
                    ranges = item.split("-")
                    if len(ranges) == 2:
                        if not ranges[0].isnumeric() or not ranges[1].isnumeric():
                            h.fatal(f"Non-numeric range {ranges} in '{input}'")
                        for cpu_number in range(int(ranges[0]), int(ranges[1]) + 1):
                            current_group.append(cpu_number)
                else:
                    # syntax: <x>
                    item_group: str | int = item
                    if item.isnumeric():
                        item_group = int(item)
                    current_group.append(item_group)
            if groups_count > 1:
                result.append(current_group)
            else:
                result = current_group
        return result
