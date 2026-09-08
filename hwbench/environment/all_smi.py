from __future__ import annotations

import functools
import json
import logging
import pathlib
import subprocess
from typing import Any

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

# Release the 'snapshot' subcommand this module is built on comes from.
MIN_VERSION = "0.26.0"

# Schema of the payload we know how to read. all-smi pins it in every object it
# serializes, which is a stronger contract than the release number.
SCHEMA = 1

BYTES_PER_MIB = 1024 * 1024


def snapshot_cmd() -> list[str]:
    """Return the all-smi command dumping the accelerators as json."""
    # --pretty=false so the output does not depend on stdout being a tty.
    return [BINARY, "snapshot", "--format", "json", "--include", "gpu", "--pretty=false"]


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
