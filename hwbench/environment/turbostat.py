from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from contextlib import suppress
from enum import Enum

from packaging.version import Version

from hwbench.bench.monitoring_structs import MonitoringContexts, MonitorMetric
from hwbench.environment.hardware import BaseHardware
from hwbench.utils.helpers import fatal, is_binary_available

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
    def __init__(self, hardware: BaseHardware, monitoring_contexts: MonitoringContexts):
        self.__output: list[str] | None = None
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
        self.monitoring_contexts = monitoring_contexts
        self.hardware = hardware
        self.process: subprocess.Popen[bytes] = None  # type: ignore[assignment]

        # Background execution support
        self._background_process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._sample_buffer: list | None = None  # Last sample as list of lines, None when cleared
        self.last_turbostat_output: int = 0
        self._stop_background = False
        self._buffer_lock = threading.Lock()
        self._background_started = False

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

        if not match:
            fatal("Monitoring/turbostat: Cannot detect turbostat version")
        current_version = Version(match.group("version"))

        print(f"Monitoring/turbostat: Detected release {current_version}")
        if current_version < self.min_release:
            fatal(f"Monitoring/turbostat: minimal expected release is {self.min_release}")

    def has(self, metric) -> bool:
        """Return if turbostat has a given metric"""
        return str(metric) in self.header.split()

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
            f"{self.hardware.get_cpu().get_logical_cores_count() - 1}",
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

    def __get_field_position(self, metric):
        """Return the field position of a given metric in the current header"""
        return self.header.split().index(str(metric))

    def __find_header_index(self, output_lines):
        """Find the index of the header line in turbostat output.

        Turbostat with --debug outputs CPU topology lines before the header.
        Topology lines start with "cpu " (lowercase), the header line contains metric names.

        Args:
            output_lines: List of turbostat output lines

        Returns:
            Index of the header line, or 0 if no topology lines found
        """
        for i, line in enumerate(output_lines):
            # Header line contains tab-separated metric names, not "cpu X pkg Y..."
            if line.startswith("usec\t"):
                return i
        return 0

    def pre_run(self):
        # Run a quick turbostat sample to detect system capabilities
        output = self.run(wait=True, interval=0.01)
        if not output:
            fatal("Failed to get turbostat output during initialization")

        # Find the header line (skip any topology debug lines at the start)
        header_idx = self.__find_header_index(output)
        self.header = output[header_idx]

        # Data lines come after the header: 1 aggregated line + per-CPU lines
        # cores_count should only count per-CPU lines, not the aggregated line
        data_lines = output[header_idx + 1 :]
        self.cores_count = len(data_lines) - 1  # Subtract 1 for the aggregated line
        if not self.has(CPUSTATS.BUSY_MHZ):
            logging.warning(
                "Busy MHz not supported by turbostat. Are you running in a VM? If not, then the CPU is probably not supported by the running kernel"
            )
        if not self.has(CPUSTATS.PACKAGE_WATTS):
            logging.warning(
                "Package watts not supported by turbostat. Are you running in a VM? If not, then the CPU is probably not supported by the running kernel"
            )
        else:
            # Initialize package power metric
            self.monitoring_contexts.PowerConsumption.CPU[PACKAGE] = MonitorMetric(PACKAGE, "Watts")
        for cores in range(self.get_cores_count()):
            # If we have CoreWatt, let's report them
            if self.has(CPUSTATS.CORE_WATTS):
                self.monitoring_contexts.PowerConsumption.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Watts")
            # If we have IPC, let's report them
            if self.has(CPUSTATS.IPC):
                self.monitoring_contexts.IPC.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "IPC")
            self.monitoring_contexts.Freq.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Mhz")

    def get_cores_count(self):
        return self.cores_count

    def reinitialize_metrics(self):
        """Reinitialize metric structures after monitoring contexts are reset.

        This recreates the MonitorMetric objects in the monitoring contexts without
        re-running turbostat. Use this after __reset_metrics() to restore the metric
        structure that turbostat will populate during monitoring.
        """
        # Initialize package power metric if available
        if self.has(CPUSTATS.PACKAGE_WATTS):
            self.monitoring_contexts.PowerConsumption.CPU[PACKAGE] = MonitorMetric(PACKAGE, "Watts")

        # Initialize per-core metrics
        for cores in range(self.get_cores_count()):
            # If we have CoreWatt, let's report them
            if self.has(CPUSTATS.CORE_WATTS):
                self.monitoring_contexts.PowerConsumption.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Watts")
            # If we have IPC, let's report them
            if self.has(CPUSTATS.IPC):
                self.monitoring_contexts.IPC.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "IPC")
            self.monitoring_contexts.Freq.CPU[f"Core_{cores}"] = MonitorMetric(f"Core_{cores}", "Mhz")

    def _get_global_packages_power(self) -> float:
        """Return the summarized packages power from current output."""
        assert self.__output is not None, "Output must be set before calling _get_global_packages_power"
        package_power = []
        header_idx = self.__find_header_index(self.__output)
        # Skip header and aggregated line, process per-core data
        for line in self.__output[header_idx + 2 :]:
            items = line.split()
            try:
                pkg_pos = self.__get_field_position(CPUSTATS.PACKAGE_WATTS)
                pkg_value = items[pkg_pos]
                package_power.append(float(pkg_value))
            except (IndexError, ValueError):
                continue
        return sum(package_power)

    def _reader_worker(self):
        """Background thread that continuously reads turbostat output and buffers samples.

        With EOL-triggered sampling, turbostat waits for stdin input before producing output,
        so we don't need to wait for initial output - it will come when we send the first trigger.
        """
        if not self._background_process or not self._background_process.stdout:
            logging.error("Turbostat reader: no process or stdout")
            return

        current_sample_lines = []
        header_seen = False

        try:
            for line in iter(self._background_process.stdout.readline, b""):
                if self._stop_background:
                    break

                decoded_line = line.decode().rstrip()
                if not decoded_line:
                    continue

                # Skip CPU topology lines (if present in output)
                if decoded_line.startswith("cpu "):
                    continue

                # Check if this is a header line (contains tab-separated column names)
                if not header_seen and "\t" in decoded_line:
                    header_seen = True
                    current_sample_lines = [decoded_line]
                    continue

                # If we've seen the header, collect lines
                if header_seen:
                    current_sample_lines.append(decoded_line)

                    # Check if this completes a sample (we have header + aggregated + per-core data)
                    # current_sample_lines contains: [header, aggregated, core_0, core_1, ...]
                    # We need: 1 (header) + 1 (aggregated) + cores_count (per-core lines)
                    if len(current_sample_lines) >= 2 + self.cores_count:
                        with self._buffer_lock:
                            # Replace the buffer with the latest sample
                            self._sample_buffer = current_sample_lines.copy()
                            logging.debug("Turbostat: buffered new sample")

                        # Reset for next sample
                        current_sample_lines = []
                        header_seen = False
                self.last_turbostat_output = time.monotonic_ns()

        except Exception as e:
            logging.error(f"Turbostat reader thread error: {e}")

    def start_background(self):
        """Start turbostat in continuous background mode.

        Turbostat will be triggered on-demand via EOL (newline) sent to stdin.
        """
        if self._background_started:
            logging.warning("Turbostat background monitoring already started")
            return

        english_env = os.environ.copy()
        english_env["LC_ALL"] = "C"

        cmd_line = [
            "taskset",
            "-c",
            f"{self.hardware.get_cpu().get_logical_cores_count() - 1}",
            "turbostat",
            "--cpu",
            "core",
            "-i",
            "100",
            "--quiet",
            "--show",
        ]

        sensors = ",".join(str(sensor) for sensor in CPUSTATS)
        cmd_line.append(sensors)

        logging.info("Starting turbostat in background mode with EOL-triggered sampling")

        self._background_process = subprocess.Popen(
            cmd_line,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            env=english_env,
            bufsize=0,  # Unbuffered
        )

        # Start a thread to monitor stderr for warnings/errors
        def stderr_monitor():
            if self._background_process and self._background_process.stderr:
                for line in self._background_process.stderr:
                    decoded = line.decode().rstrip()
                    if decoded:
                        logging.warning(f"Turbostat stderr: {decoded}")

        stderr_thread = threading.Thread(target=stderr_monitor, daemon=True)
        stderr_thread.start()

        # Start the reader thread
        self._stop_background = False
        self._reader_thread = threading.Thread(target=self._reader_worker, daemon=True)
        self._reader_thread.start()
        self._background_started = True

    def trigger_sample(self):
        """Trigger turbostat to output a sample by sending EOL to stdin.

        This sends a newline character to turbostat's stdin, which causes it
        to immediately collect and output statistics. The previous sample buffer
        is cleared to ensure we don't retrieve stale data.
        """
        if not self._background_process or not self._background_process.stdin:
            logging.error("Cannot trigger sample: no background process or stdin")
            return

        # Clear the previous sample buffer to avoid retrieving stale data
        with self._buffer_lock:
            self._sample_buffer = None
            logging.debug("Turbostat: cleared sample buffer")

        try:
            self._background_process.stdin.write(b"\n")
            self._background_process.stdin.flush()
            logging.debug("Turbostat: sent EOL trigger")
        except (BrokenPipeError, OSError) as e:
            logging.error(f"Failed to trigger turbostat sample: {e}")

    def wait_for_sample(self, timeout: float = 5.0) -> list | None:
        """Wait for a sample from turbostat.

        This method blocks until a sample appears in the buffer, or until the timeout expires.
        The sample is NOT consumed - it remains in the buffer and will be overwritten when
        a newer sample arrives.

        Args:
            timeout: Maximum time to wait in seconds (default: 5.0)

        Returns:
            Sample lines or None if timeout or no sample
        """
        start_time = time.monotonic()
        poll_interval = 0.05  # 50ms polling interval

        while time.monotonic() - start_time < timeout:
            with self._buffer_lock:
                if self._sample_buffer is not None:
                    # Return a copy of the sample WITHOUT consuming it
                    return self._sample_buffer.copy()

            # No sample yet, wait a bit
            time.sleep(poll_interval)

        # Timeout - no sample available
        return None

    def stop_background(self):
        """Stop the background turbostat process."""
        if not self._background_started:
            return

        logging.info("Stopping turbostat background monitoring")
        self._stop_background = True

        if self._background_process:
            self._background_process.terminate()
            try:
                self._background_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._background_process.kill()
                self._background_process.wait()

        if self._reader_thread:
            self._reader_thread.join(timeout=2)

        self._background_started = False
        self._background_process = None
        self._reader_thread = None

    def parse_sample(self, sample_lines: list[str]) -> None:
        """Parse a turbostat sample and update monitoring contexts.

        Args:
            sample_lines: List of output lines for a single sample
        """
        if not sample_lines:
            return

        self.__output = sample_lines

        # Find header (skip topology lines if present in test/mock data)
        header_idx = self.__find_header_index(sample_lines)
        self.header = sample_lines[header_idx]

        # Data lines: aggregated + per-core
        # cores_count should only count per-core lines, not the aggregated line
        data_lines = sample_lines[header_idx + 1 :]
        self.cores_count = len(data_lines) - 1  # Subtract 1 for the aggregated line

        # Collect overall package power consumption
        if self.has(CPUSTATS.PACKAGE_WATTS):
            self.monitoring_contexts.PowerConsumption.CPU[PACKAGE].add(self._get_global_packages_power())

        # Extract per-core information
        cpu_pos = self.__get_field_position(CPUSTATS.CPU)
        corewatt_pos = self.__get_field_position(CPUSTATS.CORE_WATTS) if self.has(CPUSTATS.CORE_WATTS) else None
        freq_pos = self.__get_field_position(CPUSTATS.BUSY_MHZ) if self.has(CPUSTATS.BUSY_MHZ) else None
        ipc_pos = self.__get_field_position(CPUSTATS.IPC) if self.has(CPUSTATS.IPC) else None

        # Skip aggregated line (first data line), process per-core lines
        for line in data_lines[1:]:
            items = line.split()
            core_nb = items[cpu_pos]

            # Some processors report corewatt in header but not for all cores, so ignore IndexError
            if corewatt_pos is not None:
                with suppress(IndexError):
                    self.monitoring_contexts.PowerConsumption.CPU[f"Core_{core_nb}"].add(float(items[corewatt_pos]))

            if freq_pos is not None:
                self.monitoring_contexts.Freq.CPU[f"Core_{core_nb}"].add(float(items[freq_pos]))

            if ipc_pos is not None:
                self.monitoring_contexts.IPC.CPU[f"Core_{core_nb}"].add(float(items[ipc_pos]))

    def get_and_parse_sample(self, precision_s: float) -> int:
        """Get the latest sample from buffer and parse it.

        This method waits for and retrieves a turbostat sample that was triggered
        earlier by trigger_sample(). The typical usage pattern is:
        1. Call trigger_sample() at the start of the monitoring loop
        2. Do monitoring work
        3. Call get_and_parse_sample() to retrieve and parse the results

        Args:
            precision_s: the monitoring loop interval (used for timeout)

        Returns:
            last_turbostat_output: when (in monotonic time) Turbostat outputed the last values
        """
        # Wait for the triggered sample to be available
        sample = self.wait_for_sample(timeout=precision_s)

        if not sample:
            fatal(f"Monitoring: timeout waiting for a turbostat sample under {precision_s}s")
            return

        # Parse the sample
        self.parse_sample(sample)
        return self.last_turbostat_output
