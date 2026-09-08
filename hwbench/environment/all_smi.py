from __future__ import annotations

import functools
import http.client
import json
import logging
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any

from hwbench.bench.monitoring_structs import (
    GPU_DESTINATIONS,
    Frequency,
    Memory,
    MonitoringContexts,
    Power,
    Temperature,
    UnitMetric,
    Utilization,
    gpu_component_name,
)
from hwbench.environment.gpu_location import locate
from hwbench.utils.external import External
from hwbench.utils.helpers import (
    IncompatibleVersion,
    MissingBinary,
    MissingHardware,
    english_env,
    is_binary_available,
    version_compatible,
)

# Inventories and monitors the accelerators. How to install it is described in
# documentation/monitoring.md#installing-all-smi.
BINARY = "all-smi"

# Release the 'snapshot' and 'api' subcommands this module is built on come from.
MIN_VERSION = "0.26.0"

# Schema of the payload we know how to read. all-smi pins it in every object it
# serializes, which is a stronger contract than the release number.
SCHEMA = 1

# Seconds between two collections of the exporter. Independent of the
# monitoring precision so a sample is never more than a second old, whatever
# the monitoring loop was configured with. Measured at 0.4% of a core.
API_INTERVAL_S = 1

# Seconds to wait for the exporter to bind its socket, and for one answer.
API_STARTUP_TIMEOUT_S = 10.0
API_TIMEOUT_S = 1.0

BYTES_PER_MIB = 1024 * 1024

# Sampled all-smi field -> (the quantity it is, whether 0 is a reading).
# GPU_DESTINATIONS says where a quantity belongs, so this table does not have
# to repeat it, and the Redfish reader reports into the same places.
#
# all-smi reports a quantity its backend cannot read as 0 rather than as a
# missing value, hence the second element: an accelerator can very well be idle
# at 0% and hold no memory, but a powered board is never at 0 W, 0 MHz or 0
# degree. Recording those would poison the minimum and the mean of a card that
# simply exposes no such sensor.
GPU_METRICS: tuple[tuple[str, type[UnitMetric], bool], ...] = (
    ("power_consumption", Power, False),
    ("frequency", Frequency, False),
    ("utilization", Utilization, True),
    ("used_memory", Memory, True),
    ("temperature", Temperature, False),
)


def snapshot_cmd() -> list[str]:
    """Return the all-smi command dumping the accelerators as json."""
    # --pretty=false so the output does not depend on stdout being a tty.
    return [BINARY, "snapshot", "--format", "json", "--include", "gpu", "--pretty=false"]


def api_cmd(sock: pathlib.Path) -> list[str]:
    """Return the all-smi command exporting the accelerator metrics on <sock>.

    '--port 0' disables the tcp listener: the exporter is reachable from this
    host only, and a benchmarked server gets no new open port.
    """
    return [
        BINARY,
        "api",
        "--port",
        "0",
        "--socket",
        str(sock),
        "--interval",
        str(API_INTERVAL_S),
        "--processes=false",
    ]


def parse_frame(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the accelerators of one all-smi payload."""
    if frame.get("schema") != SCHEMA:
        return []
    gpus = frame.get("gpus")
    return gpus if isinstance(gpus, list) else []


def unquote(value: Any) -> Any:
    """Return a vendor property without the quotes some backends keep around it.

    The NVIDIA backend reports the VBIOS version as '"97.00.FA.00.02"'.
    """
    return value.strip('"') if isinstance(value, str) else value


def gpu_inventory(gpus: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the static properties of every accelerator, keyed by hwbench index.

    all-smi identifies an accelerator by its uuid and does not number it, so the
    index is the position it was enumerated at. The vendor 'detail' map is kept
    verbatim: its keys differ between vendors and reinterpreting them here would
    only rot as new backends land in all-smi.
    """
    return {
        str(index): {
            "index": index,
            "uuid": gpu.get("uuid"),
            "name": gpu.get("name"),
            "device_type": gpu.get("device_type"),
            "memory_total_mb": (gpu.get("total_memory") or 0) // BYTES_PER_MIB,
            "detail": {key: unquote(value) for key, value in (gpu.get("detail") or {}).items()},
        }
        for index, gpu in enumerate(gpus)
    }


def run_snapshot() -> list[dict[str, Any]]:
    """Run one all-smi snapshot and return the accelerators it reports.

    Returns an empty list when the host has no accelerator: all-smi exits 1
    without writing anything when the requested section collected no device, so
    that case is a legitimate answer rather than a failure to report.

    Not going through External.run(): this is called while parsing the job
    configuration, where writing output files would be a surprising side effect.
    """
    out = subprocess.run(
        snapshot_cmd(),
        capture_output=True,
        env=english_env(),
        stdin=subprocess.DEVNULL,
    )
    if not out.stdout.strip():
        if out.returncode != 0:
            # No accelerator detected, or a release without 'snapshot'.
            logging.debug("%s: no accelerator reported: %s", BINARY, out.stderr.decode(errors="replace").strip())
        return []
    try:
        frame = json.loads(out.stdout)
    except json.decoder.JSONDecodeError:
        print(f"{BINARY}: cannot read the snapshot output, is the release >= {MIN_VERSION} ?")
        return []
    if frame.get("schema") != SCHEMA:
        print(f"{BINARY}: unsupported schema {frame.get('schema')}, expecting {SCHEMA}")
    return parse_frame(frame)


class UnixHTTPConnection(http.client.HTTPConnection):
    """An HTTPConnection over a unix socket."""

    def __init__(self, socket_path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class AllSMI(External):
    """The static inventory of the accelerators of this system."""

    def __init__(self, out_dir: pathlib.Path):
        super().__init__(out_dir)
        self.version = ""
        self.gpus: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return BINARY

    def run_cmd(self) -> list[str]:
        return snapshot_cmd()

    def parse_cmd(self, stdout: bytes, _stderr: bytes) -> dict[str, dict[str, Any]]:
        try:
            frame = json.loads(stdout)
        except json.decoder.JSONDecodeError:
            return {}
        self.gpus = gpu_inventory(parse_frame(frame))
        return self.gpus

    def run_cmd_version(self) -> list[str]:
        return [BINARY, "--version"]

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        self.version = parse_version(stdout)
        return self.version


def parse_version(stdout: bytes) -> str:
    """Return the release of an 'all-smi --version' output: 'all-smi 0.26.3'."""
    fields = stdout.split()
    return fields[-1].decode(errors="replace") if fields else ""


@functools.cache
def get_version() -> str:
    """Return the release of the installed all-smi, empty when it is missing."""
    if not is_binary_available(BINARY):
        return ""
    out = subprocess.run([BINARY, "--version"], capture_output=True, env=english_env(), stdin=subprocess.DEVNULL)
    return parse_version(out.stdout)


@functools.cache
def list_gpus() -> dict[str, dict[str, Any]]:
    """Return the accelerator inventory of this system, keyed by hwbench index.

    Every accelerator also gets its PCI address and its physical locator, see
    gpu_location.locate(). Returns an empty dict when all-smi is missing, older
    than MIN_VERSION or reports no accelerator: hwbench must keep working on
    hosts without any, and only a job loading the GPUs requires it, see
    check_requirements().
    """
    if not version_compatible(get_version(), MIN_VERSION):
        return {}
    return locate(gpu_inventory(run_snapshot()))


def check_requirements() -> list[Exception]:
    """Return why the accelerators cannot be benchmarked, if they cannot."""
    if not is_binary_available(BINARY):
        return [MissingBinary(BINARY)]
    if not version_compatible(get_version(), MIN_VERSION):
        return [IncompatibleVersion(BINARY, get_version(), MIN_VERSION)]
    if not list_gpus():
        return [MissingHardware(f"no accelerator reported by {BINARY}")]
    return []


class AllSMIMonitoring:
    """Sample the per accelerator metrics all-smi exposes.

    The stressor already reports the performance and the temperature of the
    accelerators it burns, but only for the duration of its own run and only for
    the ones it was given. This samples every accelerator of the system, along
    the whole benchmark, and adds the board power, the frequency, the
    utilization and the memory usage.

    all-smi is not forked once per monitoring iteration: initializing its
    readers costs about 800ms, which neither fits in a monitoring loop that
    polls the BMC in the same iteration, nor is acceptable on a server whose
    performance is being measured. Its exporter is instead started once per
    benchmark and polled over a unix socket, which measured at 1.4ms per sample
    and 0.4% of a core.
    """

    def __init__(self, monitoring_contexts: MonitoringContexts, gpus: dict[str, dict[str, Any]]):
        self.monitoring_contexts = monitoring_contexts
        self.gpus = gpus
        # An accelerator is identified by its uuid, the index is ours.
        self.indexes = {gpu["uuid"]: index for index, gpu in gpus.items() if gpu.get("uuid")}
        self.process: subprocess.Popen[bytes] | None = None
        self.directory: pathlib.Path | None = None
        self.sock: pathlib.Path | None = None
        self.stderr_file: pathlib.Path | None = None
        self.warned = False
        self.reinitialize_metrics()

    def get_gpus_count(self) -> int:
        return len(self.gpus)

    def reinitialize_metrics(self) -> None:
        """Create the metric entries of every detected accelerator.

        Called again after Monitoring resets its metrics, so the structures exist
        before the first sample and the output always lists every accelerator.
        """
        for index in self.gpus:
            name = gpu_component_name(index)
            for _, quantity, _ in GPU_METRICS:
                GPU_DESTINATIONS[quantity](self.monitoring_contexts)[name] = quantity(name)

    def start(self) -> None:
        """Start the metric exporter, without waiting for it to answer.

        Initializing its accelerator readers costs about 800ms, so the caller is
        expected to do the rest of its setup and then call wait_ready(): the two
        overlap instead of adding up before every benchmark.
        """
        if self.process:
            return
        self.directory = pathlib.Path(tempfile.mkdtemp(prefix="hwbench-all-smi-"))
        self.sock = self.directory / "all-smi.sock"
        self.stderr_file = self.directory / "all-smi.stderr"
        try:
            # Nothing drains the exporter's stderr along the run, so it must not
            # be a pipe: an exporter logging more than the pipe buffer holds
            # would block on write and stop answering for the rest of the
            # benchmark. A file keeps the diagnostic without that risk.
            with self.stderr_file.open("wb") as stderr:
                self.process = subprocess.Popen(
                    api_cmd(self.sock),
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    env=english_env(),
                    stdin=subprocess.DEVNULL,
                )
        except OSError as e:
            print(f"Monitoring/{BINARY}: cannot start the exporter: {e}")
            self.__cleanup()
            return

        # Not answering is expected until it has collected once, so the probes
        # of wait_ready() stay silent; a real failure during the run is reported
        # once, see get_frame().
        self.warned = True

    def wait_ready(self) -> None:
        """Wait for the exporter to serve its first collection.

        The exporter binds its socket, then collects a first time. Both are
        awaited so the first monitoring iteration already gets a value.
        """
        if not self.process or not self.sock:
            return
        deadline = time.monotonic() + API_STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                print(f"Monitoring/{BINARY}: the exporter died at startup: {self.__stderr()}")
                self.__cleanup()
                return
            if self.sock.exists() and self.get_frame() is not None:
                self.warned = False
                return
            time.sleep(0.1)
        print(f"Monitoring/{BINARY}: the exporter did not answer within {API_STARTUP_TIMEOUT_S}s")
        self.stop()

    def stop(self) -> None:
        """Stop the metric exporter."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.__cleanup()

    def __cleanup(self) -> None:
        self.process = None
        self.sock = None
        self.stderr_file = None
        if self.directory:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None

    def __stderr(self) -> str:
        """Return what the exporter logged, to be read before __cleanup()."""
        if not self.stderr_file:
            return ""
        try:
            return self.stderr_file.read_text(errors="replace").strip()
        except OSError:
            return ""

    def get_frame(self) -> dict[str, Any] | None:
        """Return the latest metrics of the exporter, None when unreachable."""
        if not self.sock:
            return None
        connection = UnixHTTPConnection(str(self.sock), API_TIMEOUT_S)
        try:
            connection.request("GET", "/snapshot?include=gpu")
            answer = connection.getresponse()
            body = answer.read()
            if answer.status != 200:
                raise OSError(f"HTTP {answer.status}")
            return json.loads(body)
        except (OSError, json.decoder.JSONDecodeError) as e:
            if not self.warned:
                # Only reported once: a monitoring iteration is short and a
                # broken exporter would flood the output otherwise.
                print(f"Monitoring/{BINARY}: cannot read the accelerator metrics: {e}")
                self.warned = True
            return None
        finally:
            connection.close()

    def sample(self) -> None:
        """Collect one sample of every accelerator metric."""
        if not self.process:
            return
        if self.process.poll() is not None:
            print(f"Monitoring/{BINARY}: the exporter stopped, no more GPU metrics: {self.__stderr()}")
            self.__cleanup()
            return
        frame = self.get_frame()
        if frame is None:
            return
        for position, gpu in enumerate(parse_frame(frame)):
            index = self.index_of(position, gpu.get("uuid"))
            if index is None:
                # An accelerator that was not part of the inventory, i.e. one
                # that appeared after a driver reset: there is no metric to add
                # it to, and reporting a partial serie would be worse.
                continue
            name = gpu_component_name(index)
            for field, quantity, zero_is_valid in GPU_METRICS:
                value = gpu.get(field)
                if not isinstance(value, (int, float)) or (not value and not zero_is_valid):
                    continue
                if field == "used_memory":
                    value = value / BYTES_PER_MIB
                GPU_DESTINATIONS[quantity](self.monitoring_contexts)[name].add(float(value))

    def index_of(self, position: int, uuid: Any) -> str | None:
        """Return the inventory index of an accelerator of a frame."""
        index = self.indexes.get(uuid)
        if index is not None:
            return index
        # A backend that does not report a stable uuid still enumerates the
        # accelerators in the order the inventory saw them.
        return str(position) if str(position) in self.gpus else None
