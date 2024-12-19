import os
import re
import subprocess
from enum import Enum
from packaging.version import Version
from ..environment.hardware import BaseHardware
from ..bench.monitoring_structs import MonitorMetric, CPUContext, PowerContext
from ..utils.helpers import is_binary_available, fatal

CORE = "core"
PACKAGE = "package"


class CPUSTATS(Enum):
    NODE = "Node"
    CORE = "Core"
    CPU = "CPU"
    BUSY_PERCENT = "Busy%"
    BUSY_MHZ = "Bzy_MHz"
    TSC_MHZ = "TSC_MHz"
    IPC = "IPC"
    C1_PERCENT = "C1%"
    C2_PERCENT = "C2%"
    CORE_WATTS = "CorWatt"
    PACKAGE_WATTS = "PkgWatt"

    def __str__(self) -> str:
        """Returns the field name."""
        return self.value


class Turbostat:
    def __init__(
        self,
        hardware: BaseHardware,
        freq_metrics: dict[str, dict[str, dict[str, MonitorMetric]]] = {},
        power_metrics: dict[str, dict[str, dict[str, MonitorMetric]]] = {},
    ):
        self.__output = None
        self.cores_count = 0
        self.sensor_list = {
            CPUSTATS.NODE,
            CPUSTATS.CORE,
            CPUSTATS.CPU,
            CPUSTATS.BUSY_PERCENT,
            CPUSTATS.BUSY_MHZ,
            CPUSTATS.TSC_MHZ,
            CPUSTATS.IPC,
            CPUSTATS.C1_PERCENT,
            CPUSTATS.C2_PERCENT,
            CPUSTATS.CORE_WATTS,
            CPUSTATS.PACKAGE_WATTS,
        }
        self.min_release = Version("2022.04.16")
        self.header = ""
        self.freq_metrics = freq_metrics
        self.power_metrics = power_metrics
        self.hardware = hardware
        self.process: subprocess.Popen[bytes] = None  # type: ignore[assignment]
        self.freq_metrics[str(CPUContext.CPU)] = {}  # type: ignore[no-redef]
        self.power_metrics[str(PowerContext.CPU)] = {}  # type: ignore[no-redef]

        # Let's make a first quick run to detect system
        self.check_version()
        self.pre_run()

    def check_version(self):
        english_env = os.environ.copy()
        english_env["LC_ALL"] = "C"

        if not is_binary_available("turbostat"):
            fatal("Missing turbostat binary, please install it.")

        self.process = subprocess.Popen(
            ["turbostat", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=english_env,
            stdin=subprocess.DEVNULL,
        )
        # turbostat version 2022.04.16 - Len Brown <lenb@kernel.org>
        match = re.search(
            r"turbostat version (?P<version>[0-9]+\.[0-9]+\.[0-9]+).*",
            str(self.get_process_output()),
        )

        current_version = Version(match.group("version"))
        if not match:
            fatal("Monitoring/turbostat: Cannot detect turbostat version")

        print(f"Monitoring/turbostat: Detected release {current_version}")
        if current_version < self.min_release:
            fatal(f"Monitoring/turbostat: minimal expected release is {self.min_release}")

    def reset_metrics(self, power_metrics=None):
        if power_metrics is not None:
            self.power_metrics = power_metrics
        if str(PowerContext.CPU) not in self.power_metrics:
            self.power_metrics[str(PowerContext.CPU)] = {}
        self.power_metrics[str(PowerContext.CPU)][PACKAGE] = MonitorMetric(PACKAGE, "Watts")

        for cores in range(self.get_cores_count()):
            # If we have CoreWatt, let's report them
            if self.has(CPUSTATS.CORE_WATTS):
                self.power_metrics[str(PowerContext.CPU)][f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Watts")
            self.freq_metrics[str(CPUContext.CPU)][f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Mhz")
        return self.freq_metrics, self.power_metrics

    def has(self, metric) -> bool:
        """Return if turbostat has a given metric"""
        return str(metric) in self.__get_column_header().split()

    def get_sensors(self):
        """Return the list of sensors."""
        return self.sensor_list.keys

    def run(self, interval: float = 1, wait=False):
        """Execute turbostats"""
        # [root@criteo-conformity hwmon1]#  turbostat -c core -q --interval 1 -n1  -s Node,Core,CPU,Busy%,Bzy_MHz,TSC_MHz,CorWatt,PkgWatt,IPC,C1%,C2%
        # Node	Core	CPU	Busy%	Bzy_MHz	TSC_MHz	IPC	C1%	C2%	CorWatt	PkgWatt
        # -	-	-	0.02	2812	2321	0.43	1.92	99.11	0.35	13.52
        # 0	0	0	0.03	2991	2296	0.63	1.99	97.98	0.01	13.39
        # 0	1	1	0.02	2962	2297	0.35	1.99	97.99	0.01
        # 0	2	2	0.02	2968	2297	0.36	2.37	97.61	0.01
        # 0	3	3	0.02	2968	2297	0.36	2.26	97.72	0.01
        # 0	4	4	0.02	2962	2297	0.36	2.16	97.83	0.01
        # 0	5	5	0.02	2965	2297	0.34	2.14	97.84	0.01
        # 0	6	6	0.02	2966	2297	0.37	2.13	97.85	0.01
        # 0	7	7	0.02	2954	2297	0.37	2.03	97.96	0.01
        # 1	8	8	0.02	2900	2297	0.27	2.01	97.97	0.01
        # 1	9	9	0.02	2920	2297	0.35	2.20	97.79	0.01
        # 1	10	10	0.02	2887	2297	0.35	1.89	98.09	0.01
        # 1	11	11	0.02	2898	2297	0.36	2.18	97.81	0.01
        # 1	12	12	0.02	2901	2297	0.35	2.26	97.72	0.01
        # 1	13	13	0.02	2931	2297	0.36	2.64	97.34	0.01
        # 1	14	14	0.02	2916	2297	0.34	2.24	97.74	0.01
        # 1	15	15	0.04	2396	2297	0.39	2.14	97.83	0.01
        english_env = os.environ.copy()
        english_env["LC_ALL"] = "C"
        # We can override the interval time at runtime
        cmd_line = [
            "taskset",
            "-c",
            f"{self.hardware.get_cpu().get_logical_cores_count()-1}",
            "turbostat",
            "--cpu",
            "core",
            "--quiet",
            "--interval",
            str(interval),
            "--num_iterations",
            "1",
            "--show",
        ]
        sensors = ""
        for sensor in CPUSTATS:
            if not sensors:
                sensors += f"{sensor}"
            else:
                sensors += f",{sensor}"
        cmd_line.append(sensors)

        self.process = subprocess.Popen(
            cmd_line,
            stdout=subprocess.PIPE,
            env=english_env,
            stdin=subprocess.DEVNULL,
        )

        if wait:
            return self.get_process_output()

    def get_process_output(self):
        out, _ = self.process.communicate()
        self.__output = out.decode().splitlines()
        return self.__output

    def __get_column_header(self):
        """Return the turbostat column header"""
        return self.header

    def __set_column_header(self, header):
        """Set the turbostat column header"""
        self.header = header

    def __get_field_position(self, metric):
        """Return the field position of a given metric"""
        return self.__get_column_header().split().index(str(metric))

    def pre_run(self):
        # Even if self.run is setting __output, forcing here helps mocking
        self.__output = self.run(wait=True, interval=0.01)
        # Header is two lines
        header_size = 2
        self.cores_count = len(self.__output) - header_size
        self.__set_column_header(self.__output[0])
        self.reset_metrics()

    def parse(self):
        """Parse the run() output"""
        self.get_process_output()

        # Header is two lines
        header_size = 2
        self.cores_count = len(self.__output) - header_size

        self.__set_column_header(self.__output[0])

        # Collecting the overall packages power consumption
        self.power_metrics[str(PowerContext.CPU)][PACKAGE].add(self.get_global_packages_power())
        # self.__results[PACKAGE].add(self.get_global_packages_power())

        # We skip the header and then extract all cores informations
        for line in self.get_output()[header_size:]:
            items = line.split()
            core_nb = items[int(self.__get_field_position(CPUSTATS.CPU))]
            if self.has(CPUSTATS.CORE_WATTS):
                try:
                    self.power_metrics[str(PowerContext.CPU)][f"Core_{core_nb}"].add(
                        float(items[int(self.__get_field_position(CPUSTATS.CORE_WATTS))])
                    )
                except IndexError:
                    # Some processors reports the corewatt in the header but not for all cores ...
                    # So let's ignore if the metrics does not exist for this core
                    pass

            self.freq_metrics[str(CPUContext.CPU)][f"Core_{core_nb}"].add(
                float(items[int(self.__get_field_position(CPUSTATS.BUSY_MHZ))])
            )

    def get_packages_power(self):
        """Return the individual package power."""
        package_power = []
        for line in self.get_output()[2:]:
            pkgwatt = self.get_output_fields(
                line,
                [
                    self.__get_field_position(CPUSTATS.PACKAGE_WATTS),
                ],
            )

            if isinstance(pkgwatt[0], str):
                package_power.append(float(pkgwatt[0]))
        return package_power

    def get_global_packages_power(self):
        """Return the summarized packages power."""
        return sum(self.get_packages_power())

    def get_results(self):
        return self.__results

    def get_output(self):
        return self.__output

    def get_output_field(self, line, field):
        try:
            return line.split()[int(field)]
        except IndexError:
            return None

    def get_output_fields(self, line, fields):
        output = []
        for field in fields:
            output.append(self.get_output_field(line, field))
        return output

    def get_core_info(self, core_nb, info):
        # We ignore the two header lines and jumps to the core itself
        header_size = 2  # lines
        line = self.get_output()[core_nb + header_size]
        core, result = self.get_output_fields(
            line,
            [self.__get_field_position(CPUSTATS.CPU), self.__get_field_position(info)],
        )
        if int(core) == core_nb:
            return result
        return None

    def get_core_infos(self, core_nb, infos):
        # We ignore the two header lines and jumps to the core itself
        header_size = 2  # lines
        line = self.get_output()[core_nb + header_size]
        results = self.get_output_fields(line, [self.__get_field_position(CPUSTATS.CPU)] + infos)
        if int(results[0]) == core_nb:
            return results[1:]
        return None

    def get_cores_count(self):
        return self.cores_count
