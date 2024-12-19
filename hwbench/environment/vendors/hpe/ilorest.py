import json
import subprocess
from ....utils import helpers as h
from ....utils.external import External


class Ilorest(External):
    def run_cmd(self) -> list[str]:
        return ["ilorest", "get", "--json", "--nologo", "--select", "Bios."]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.decoder.JSONDecodeError:
            h.fatal(stdout)

    def run_cmd_version(self) -> list[str]:
        return ["ilorest", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    @property
    def name(self) -> str:
        return "ilorest-bios"


class IlorestServerclone(External):
    def run_cmd(self) -> list[str]:
        """This creates a file named ilorest_clone.json in the output directory"""
        return ["ilorest", "serverclone", "save", "--nologo", "--auto"]

    def parse_cmd(self, stdout: bytes, _stderr: bytes):
        return None

    def run_cmd_version(self) -> list[str]:
        return ["ilorest", "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> bytes:
        self.version = stdout.split()[3]
        return self.version

    @property
    def name(self) -> str:
        return "ilorest-serverclone"


class ILOREST:
    """Main class to discuss with the ILO bmc."""

    logged = False

    def __init__(self):
        if not h.is_binary_available("ilorest"):
            h.fatal("HPE vendor requires 'ilorest' tool, please install it.")
        self.login()

    def __del__(self):
        """Destructor."""
        # Let's free the session we have set
        if self.logged:
            self.__ilorest("logout")

    def __ilorest(self, arguments, nocache=True):
        commands = None
        output = None
        if isinstance(arguments, str):
            commands = arguments.split()
        elif isinstance(arguments, list):
            commands = arguments
        else:
            raise TypeError("arguments should be either a string or list type")

        commands.append("--nologo")
        if nocache:
            commands.append("--nocache")
        p = subprocess.Popen(["/usr/sbin/ilorest"] + commands, stdout=subprocess.PIPE)
        output, _ = p.communicate()
        return p.returncode, output.replace(b"Discovering data...Done", b"")

    def login(self, last_try=False):
        if self.logged:
            return True
        return_code, _ = self.__ilorest("login")
        # We cannot login because of CreateLimitReachedForResource
        # Let's reset the bmc and retry
        if return_code == 32:
            h.fatal("Cannot login to local ilo, return_code = {}".format(return_code))
        elif return_code == 64:
            h.fatal("Cannot login to local ilo", details="BMC is missing")
        elif return_code == 0:
            self.logged = True
            return True
        else:
            h.fatal("Cannot login to local ilo, return_code = {}".format(return_code))

    def raw_get(self, endpoint, to_json=False):
        """Perform a raw get."""
        command = "rawget /redfish/v1{}".format(endpoint)
        return_code, rawget = self.__ilorest(command)
        if return_code != 0:
            raise subprocess.CalledProcessError(returncode=return_code, cmd=command)
        if not to_json:
            return rawget
        return json.loads(rawget)

    def get(self, endpoint, select=None, filter=None, to_json=False):
        """Perform a get."""
        command = "get {}".format(endpoint)
        if select:
            command += " --select {}".format(select)
        if filter:
            command += ' --filter "{}"'.format(filter)
        command += " -j"
        return_code, get = self.__ilorest(command)
        if return_code != 0:
            raise subprocess.CalledProcessError(returncode=return_code, cmd=command)
        if not to_json:
            return get
        return json.loads(get)

    def list(self, select, filter=None, to_json=False):
        """Perform a get."""
        command = "list "
        if select:
            command += " --select {}".format(select)
        if filter:
            command += ' --filter "{}"'.format(filter)
        command += " -j"
        return_code, get = self.__ilorest(command)
        if return_code != 0:
            raise subprocess.CalledProcessError(returncode=return_code, cmd=command)
        if not to_json:
            return get
        return json.loads(get)

    def get_bmc_ipv4(self):
        """Return the BMC IPV4 address"""
        # If no url provided in the configuration file, let's detect it via ilorest
        bmc_netconfig = self.list(select="ethernetinterface", filter="id=1", to_json=True)
        if bmc_netconfig:
            # On multi-node chassis, the ethernetinterface is a list
            # On single-node chassis, the ethernetinterface is a dict
            # Let's ensure we always have a list for get a single parsing.
            if isinstance(bmc_netconfig, dict):
                bmc_netconfig = [bmc_netconfig]
            for nc in bmc_netconfig:
                if "Manager Dedicated Network Interface" in nc.get("Name"):
                    ipv4 = nc.get("IPv4Addresses")
                    if ipv4:
                        return ipv4[0].get("Address")
