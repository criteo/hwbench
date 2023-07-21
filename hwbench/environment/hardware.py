import os
import pathlib
import logging


class Hardware:
    # from conformity
    @staticmethod
    def get_dmi_from_sysfs(entry, root_path="/sys/devices/virtual/dmi/id/"):
        """Extract DMI & BMC information from the host."""
        try:
            return pathlib.Path(root_path + entry).read_text().replace("\n", "")
        except Exception as error:
            logging.error(f"Could not get dmi information {error}")
            return ""

    def dump(self):
        return {
            # TODO: more, or even dmidecode parsing
            "vendor": self.get_dmi_from_sysfs("sys_vendor"),
            "product": self.get_dmi_from_sysfs("product_name"),
            "serial": self.get_dmi_from_sysfs("product_serial"),
            "bios": {
                "version": self.get_dmi_from_sysfs("bios_version"),
                "release": self.get_dmi_from_sysfs("bios_release"),
            },
            "sysconf_threads": os.sysconf("SC_NPROCESSORS_ONLN"),
        }
