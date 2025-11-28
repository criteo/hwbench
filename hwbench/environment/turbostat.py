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
        self.monitoring_contexts = monitoring_contexts
        self.hardware = hardware
        self.process: subprocess.Popen[bytes] = None  # type: ignore[assignment]

        # Background execution support
        self._background_process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._sample_buffer: tuple[int, list] | None = None  # Last sample as (timestamp, lines), None when consumed
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

        current_version = Version(match.group("version"))
        if not match:
            fatal("Monitoring/turbostat: Cannot detect turbostat version")

        print(f"Monitoring/turbostat: Detected release {current_version}")
        if current_version < self.min_release:
            fatal(f"Monitoring/turbostat: minimal expected release is {self.min_release}")

    def has(self, metric) -> bool:
        """Return if turbostat has a given metric"""
        return str(metric) in self.header.split()

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

    def _get_global_packages_power(self):
        """Return the summarized packages power from current output."""
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
        """Background thread that continuously reads turbostat output and buffers samples."""
        if not self._background_process or not self._background_process.stdout:
            return

        current_sample_lines = []
        header_seen = False
        sample_timestamp_ns = None

        try:
            for line in iter(self._background_process.stdout.readline, b""):
                if self._stop_background:
                    break

                decoded_line = line.decode().rstrip()
                if not decoded_line:
                    continue

                # Skip CPU topology lines (from --debug output)
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

                    # Extract timestamp from the aggregated line (first data line after header)
                    # Format with --debug: usec\tTime_Of_Day_Seconds\t...
                    if len(current_sample_lines) == 2:  # First data line (aggregated metrics)
                        try:
                            fields = decoded_line.split()
                            # Check if we have timestamp fields (not dashes)
                            if len(fields) >= 2 and fields[0] != "-" and fields[1] != "-":
                                # usec is the microseconds spent collecting this sample
                                collection_time_us = int(fields[0])
                                # Time_Of_Day_Seconds is the timestamp when collection finished
                                time_of_day_seconds = float(fields[1])
                                # Convert to nanoseconds for consistency
                                sample_timestamp_ns = int(time_of_day_seconds * 1e9)

                                # Log if collection took unusually long (> 100ms)
                                if collection_time_us > 100000:
                                    logging.warning(
                                        f"Turbostat collection took {collection_time_us / 1000:.1f}ms "
                                        f"(threshold: 100ms)"
                                    )
                            else:
                                # No timestamp available (running without --debug or test data)
                                sample_timestamp_ns = time.time_ns()
                        except (ValueError, IndexError) as e:
                            logging.warning(f"Failed to parse turbostat timestamp: {e}")
                            sample_timestamp_ns = time.time_ns()

                    # Check if this completes a sample (we have header + aggregated + per-core data)
                    # current_sample_lines contains: [header, aggregated, core_0, core_1, ...]
                    # We need: 1 (header) + 1 (aggregated) + cores_count (per-core lines)
                    if len(current_sample_lines) >= 2 + self.cores_count:
                        # We have a complete sample, store it with turbostat's timestamp
                        if sample_timestamp_ns is None:
                            sample_timestamp_ns = time.monotonic_ns()

                        with self._buffer_lock:
                            # Replace the buffer with only the last sample (timestamp, lines)
                            self._sample_buffer = (sample_timestamp_ns, current_sample_lines.copy())

                        # Reset for next sample
                        current_sample_lines = []
                        header_seen = False
                        sample_timestamp_ns = None

        except Exception as e:
            logging.error(f"Turbostat reader thread error: {e}")

    def start_background(self, interval: float = 1.0):
        """Start turbostat in continuous background mode.

        Args:
            interval: Sampling interval in seconds
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
            "--quiet",
            "--debug",
            "--interval",
            str(interval),
            "--show",
        ]

        sensors = ",".join(str(sensor) for sensor in CPUSTATS)
        cmd_line.append(sensors)

        logging.info(f"Starting turbostat in background mode with interval={interval}s")

        self._background_process = subprocess.Popen(
            cmd_line,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=english_env,
            stdin=subprocess.DEVNULL,
        )

        # Start the reader thread
        self._stop_background = False
        self._reader_thread = threading.Thread(target=self._reader_worker, daemon=True)
        self._reader_thread.start()
        self._background_started = True

    def wait_for_sample(self, timeout: float = 5.0) -> tuple[int | None, list | None]:
        """Wait for a sample from turbostat.

        This method blocks until a sample appears in the buffer, or until the timeout expires.
        When a sample is found, it is consumed (removed from the buffer).

        Args:
            timeout: Maximum time to wait in seconds (default: 5.0)

        Returns:
            Tuple of (timestamp_ns, sample_lines) or (None, None) if timeout or no sample
        """
        start_time = time.monotonic()
        poll_interval = 0.05  # 50ms polling interval

        while time.monotonic() - start_time < timeout:
            with self._buffer_lock:
                if self._sample_buffer is not None:
                    # Get the sample and set buffer to None (consumed)
                    timestamp, sample_lines = self._sample_buffer
                    self._sample_buffer = None
                    return timestamp, sample_lines

            # No sample yet, wait a bit
            time.sleep(poll_interval)

        # Timeout - no sample available
        return None, None

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

    def parse_sample(self, sample_lines):
        """Parse a turbostat sample and update monitoring contexts.

        Args:
            sample_lines: List of output lines for a single sample
        """
        if not sample_lines:
            return

        self.__output = sample_lines

        # Find header (skip topology lines if present in test/mock data)
        header_idx = self.__find_header_index(self.__output)
        self.header = self.__output[header_idx]

        # Data lines: aggregated + per-core
        # cores_count should only count per-core lines, not the aggregated line
        data_lines = self.__output[header_idx + 1 :]
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

    def get_and_parse_sample(self, precision_s: float) -> int | None:
        """Get the next sample from buffer, parse it, and handle synchronization.

        This is the main interface for the monitoring loop. It handles:
        - Waiting for the next unconsumed sample from turbostat
        - Parsing the sample data
        - Calculating timing information

        Args:
            is_first_iteration: True if this is the first monitoring iteration
            verbose: Whether to print diagnostic messages

        Returns:
            Tuple of (sample_available, sample_timestamp_ns, time_diff_ms)
            - sample_available: Whether a sample was found and parsed
            - sample_timestamp_ns: Wall-clock timestamp of the sample (or None if unavailable)
        """
        # Wait for the next sample (blocks until available or timeout)
        sample_timestamp, sample = self.wait_for_sample(timeout=precision_s + 1)

        if not sample:
            fatal(f"Monitoring: timeout waiting for a turbostat sample under {precision_s + 1}s")
            return None

        # Parse the sample
        self.parse_sample(sample)

        # No time_diff_ms calculation needed - we're consuming samples sequentially now
        return sample_timestamp

    def calculate_sync_offset(self, sample_timestamp_ns: int, monitoring_start_ns: int, verbose: bool = True) -> int:
        """Calculate synchronization offset and return adjusted monitoring start time.

        This adjusts the monitoring loop's start time to align with turbostat's
        actual first sample timing.

        Args:
            sample_timestamp_ns: Wall-clock timestamp of turbostat's first sample
            monitoring_start_ns: Monotonic start time of monitoring loop
            verbose: Whether to print diagnostic messages

        Returns:
            Adjusted monitoring_start_ns aligned with turbostat timing
        """
        # Calculate the wall-clock equivalent of our monotonic start time
        wallclock_now = time.time_ns()
        monotonic_now = time.monotonic_ns()
        wallclock_start = wallclock_now - (monotonic_now - monitoring_start_ns)

        # Calculate the offset between our start and turbostat's first sample
        sync_offset_ms = (sample_timestamp_ns - wallclock_start) / 1e6
        if verbose and abs(sync_offset_ms) > 50:  # Only report if offset is significant
            print(f"Monitoring: synchronized with turbostat (offset: {sync_offset_ms:+.1f}ms)")

        # Adjust our effective start time to align with turbostat
        # Convert turbostat's wall-clock time back to monotonic time base
        adjusted_start_ns = monotonic_now - (wallclock_now - sample_timestamp_ns)
        return adjusted_start_ns
