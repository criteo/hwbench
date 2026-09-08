from __future__ import annotations

import functools
import json
import pathlib
import re
import subprocess
import tempfile
from configparser import RawConfigParser
from typing import Any

from hwbench.bench.benchmark import ExternalBench
from hwbench.bench.engine import EngineBase, EngineModuleBase, Resource
from hwbench.bench.parameters import BenchmarkParameters
from hwbench.environment.all_smi import list_gpus
from hwbench.utils import helpers as h

# The workloads of pantheon, grouped the way pantheon groups them: an engine
# module is one of its suites and an engine_module_parameter one of its tests,
# so 'engine_module=memory' + 'engine_module_parameter=all' runs every memory
# workload as its own benchmark.
#
# Mirrors the SUITES table of pantheon 1.2.x. A test pantheon knows and this
# table does not is refused by the configuration validation rather than passed
# through: an unknown '--test' makes pantheon exit before running anything.
SUITES: dict[str, list[str]] = {
    "baseline": ["baseline_metrics"],
    "core": [
        "voltage",
        "incinerator",
        "fp64_virus",
        "int_virus",
        "mma_virus",
        "sfu_stress",
        "pulse_virus",
        "tensor_virus",
        "transformer_virus",
        "omni_virus",
    ],
    "memory": [
        "memory_thermal_asym",
        "memory_cache_fracture",
        "memory_retention_bake",
        "memory_retention",
        "memory_bank_thrash",
        "memory_write",
        "memory_write_agg",
        "memory_read",
        "memory_read_agg",
        "cache_lat",
        "atomic_virus",
    ],
    "interconnect": [
        "tlb_avalanche",
        "scheduler",
        "pcie_bandwidth",
        "p2p_thrasher",
        "all_reduce",
        "memory_pc_pingpong",
        "memory_tsv_thrasher",
    ],
    "diagnostics": [
        "march_test",
        "galpat",
        "memory_hammer",
        "memory_retention",
        "ras_validator",
    ],
    "fixedFunction": ["rt_virus", "media_enc_virus"],
    "inference": [
        "llm_decode",
        "llm_prefill",
        "kv_cache_churn",
        "fused_attention",
        "rope_stress",
        "quantized_gemm",
        "serving_mix",
        "speculative_decode",
        "moe_router",
    ],
    "training": ["transformer_train_step"],
    "runtime": ["allocation_fragmentation", "graph_replay"],
    "ai_auxiliary": ["rag_embedding", "vision_encoder"],
}

# Custom parameters that end up on the pantheon command line.
TOOL_PARAMETERS = ["gpu_memory_percent", "verify", "platform"]

PLATFORMS = ["auto", "cuda", "hip", "mock"]

# The workload the kernel cache is warmed up with. 'baseline_metrics' measures
# an idle accelerator, so the warm up compiles everything without loading
# anything, and the accelerators start the first benchmark cold.
WARMUP_TEST = "baseline_metrics"
WARMUP_RUNTIME = 1

# pantheon writes its machine readable report next to its other output, and
# logs where. The path is relative to the directory it ran in, which
# External.run() sets to the output directory of the benchmark.
REPORT_LINE = re.compile(r"Snapshot saved to:\s*(?P<path>\S+)")

# Reported metric -> key of the pantheon report row it comes from. Every value
# is a number, and 'N/A' when the accelerator exposes no such sensor.
GPU_NUMBERS = {
    "score": "Score",
    "score_variance_percent": "Throughput Variance (%)",
    "temperature_avg_celsius": "Avg Temp (C)",
    "temperature_max_celsius": "Max Temp (C)",
    "memory_temperature_avg_celsius": "Avg Mem Temp (C)",
    "memory_temperature_max_celsius": "Max Mem Temp (C)",
    "power_avg_watts": "Avg Power (W)",
    "power_max_watts": "Max Power (W)",
    "clock_avg_mhz": "Avg Clock(MHz)",
    "clock_min_mhz": "Min Clock (MHz)",
    "clock_max_mhz": "Max Clock (MHz)",
    "utilization_avg_percent": "Avg GPU Util (%)",
    "utilization_max_percent": "Max GPU Util (%)",
    "memory_peak_mb": "Peak Memory (MiB)",
    "memory_total_mb": "Memory Total (MiB)",
    "energy_wh": "Energy (Wh)",
    "thermal_rise_celsius": "Thermal Rise (C)",
    "throttle_seconds": "Throttle Time (s)",
    "efficiency": "Efficiency",
    "pcie_gen": "PCIe Gen",
    "fan_max_percent": "Max Fan (%)",
    "volts_core_mv": "Volts Core (mV)",
    "volts_soc_mv": "Volts SoC (mV)",
}

# Same, for the values that are free text.
GPU_STRINGS = {
    "unit": "Unit",
    "pcie_width": "PCIe Width",
    "throttle_reason": "Limit Reason",
    "failure_stage": "Failure Stage",
    "failure_reason": "Failure Reason",
    "ras_status": "RAS Status",
    "ras_error_delta": "RAS Error Delta",
}

# Units pantheon reports when a workload did not measure anything.
NO_UNIT = ("", "ERR", "SKIP")

# What pantheon reports for a quantity the accelerator does not expose.
NOT_AVAILABLE = "N/A"


def number(value: Any) -> float | None:
    """Return a report value as a number, None when it has none.

    pantheon reports a quantity the accelerator does not expose as the string
    'N/A', so a row is a mix of numbers and placeholders.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text(value: Any) -> str | None:
    """Return a report value as a string, None when it has none."""
    return None if value in (None, NOT_AVAILABLE) else str(value)


@functools.cache
def build_kernels(binary: str, platform: str) -> None:
    """Compile the pantheon kernels, before anything is measured.

    pantheon builds its CUDA or HIP kernels on first use, which takes from a
    few seconds to several minutes. Left to the first benchmark, that lands
    inside its monitored window: it would report accelerators idling while the
    compiler runs, and a runtime the job never spent stressing anything.

    There is no build-only mode, so the shortest possible run is used to trigger
    it. pantheon keys its build cache on the platform alone -- not on the
    workload nor on the accelerators -- so one run compiles every workload, and
    this is cached on the platform for the same reason. The accelerator
    selection is left to pantheon: an idle measurement does not care which one
    it reads, and asking for one per job would re-run this for nothing.

    The report of that run is thrown away with the directory it is written in:
    it is not a benchmark, and it has no place in the results.
    """
    args = [binary, "--test", WARMUP_TEST, "--duration", str(WARMUP_RUNTIME), "--mem", "1", "--skip_verify"]
    if platform:
        args += ["--platform", platform]

    print(f"Startup: compiling the {binary} kernels, this can take a few minutes")
    with tempfile.TemporaryDirectory(prefix="hwbench-pantheon-") as out_dir:
        out = subprocess.run(args, capture_output=True, cwd=out_dir, env=h.english_env(), stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        # 'make -k' keeps building after a failed target, so a non-zero status
        # can still leave most workloads usable: report it and let the
        # benchmarks tell what is actually missing.
        print(f"WARNING: {binary} reported a problem while compiling its kernels:")
        print(out.stdout.decode(errors="replace").strip())
        print(out.stderr.decode(errors="replace").strip())


class EngineModuleSuite(EngineModuleBase):
    """This class implements the EngineModuleBase for one pantheon suite."""

    def __init__(self, engine: EngineBase, engine_module_name: str):
        super().__init__(engine, engine_module_name)
        self.engine_module_name = engine_module_name
        self.load_module_parameter()

    def load_module_parameter(self):
        for test in SUITES[self.engine_module_name]:
            self.add_module_parameter(test)

    def generate_benchmarks(self, config: dict[str, str]) -> list[dict[str, Any]]:
        """Forward the engine custom parameters to every benchmark.

        They are only read from the job configuration here, and
        BenchmarkParameters is otherwise unaware of them. They also end up in
        results.json, recording what was asked of the tool.
        """
        return [{key: config[key] for key in TOOL_PARAMETERS if key in config}]

    def validate_module_parameters(self, p: BenchmarkParameters) -> str:
        msg = super().validate_module_parameters(p)
        Pantheon(self, p)
        return msg

    def run_cmd(self, p: BenchmarkParameters):
        return Pantheon(self, p).run_cmd()

    def run(self, p: BenchmarkParameters):
        return Pantheon(self, p).run()

    def fully_skipped_job(self, p) -> bool:
        return Pantheon(self, p).fully_skipped_job()

    def warmup(self, p: BenchmarkParameters) -> None:
        build_kernels(
            self.get_engine().get_binary(),
            str(p.get_custom_parameters().get("platform", "")),
        )


class Engine(EngineBase):
    """The main pantheon class."""

    resources = (Resource.GPU,)
    # The release the json report, the '--gpu' list and the suites below come from.
    min_version = "1.2.0"

    def __init__(self):
        super().__init__("pantheon", "pantheon")
        for suite in SUITES:
            self.add_module(EngineModuleSuite(self, suite))
        self.custom_parameters_validators = {
            "gpu_memory_percent": self.validate_gpu_memory_percent,
            "verify": self.validate_verify,
            "platform": self.validate_platform,
        }

    def validate_gpu_memory_percent(self, gpu_memory_percent: str) -> str | None:
        """Validate the gpu_memory_percent syntax."""
        if not gpu_memory_percent.isnumeric() or not 1 <= int(gpu_memory_percent) <= 99:
            # The bounds are pantheon's own: it refuses to run outside of them.
            return f"'{gpu_memory_percent}' is not a percentage of the VRAM between 1 and 99"
        return None

    def validate_verify(self, verify: str) -> str | None:
        """Validate the verify syntax."""
        if verify.lower() not in RawConfigParser.BOOLEAN_STATES:
            return f"'{verify}' is not a boolean value"
        return None

    def validate_platform(self, platform: str) -> str | None:
        """Validate the platform syntax."""
        if platform not in PLATFORMS:
            return f"Unknown platform='{platform}', expecting one of {PLATFORMS}"
        return None

    def run_cmd_version(self) -> list[str]:
        return [
            self.get_binary(),
            "--version",
        ]

    def run_cmd(self) -> list[str]:
        return []

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        # 'pantheon 1.2.0', possibly with a pre-release suffix. A binary printing
        # nothing leaves the version empty, which check_requirements() reports as
        # too old rather than crashing here.
        fields = stdout.split()
        self.version = fields[-1].decode() if fields else ""
        return self.version

    def parse_cmd(self, stdout: bytes, stderr: bytes):
        return {}


class Pantheon(ExternalBench):
    """The pantheon stressor."""

    def __init__(self, engine_module: EngineModuleBase, parameters: BenchmarkParameters):
        ExternalBench.__init__(self, engine_module, parameters)
        self.suite = engine_module.get_name()
        self.test = parameters.get_engine_module_parameter()
        if self.test not in SUITES.get(self.suite, []):
            raise LookupError(f"Unknown pantheon test {self.test} in suite {self.suite}")
        self.gpu_list = ",".join(str(gpu) for gpu in parameters.get_pinned_gpus())

    @property
    def name(self) -> str:
        return self.engine_module.get_engine().get_name()

    def run_cmd(self) -> list[str]:
        custom = self.parameters.get_custom_parameters()
        # pantheon is not pinned on purpose: the load is on the accelerators,
        # constraining the feeding threads would only distort the measurement.
        args = [
            self.engine_module.get_engine().get_binary(),
            "--test",
            self.test,
            "--duration",
            str(self.parameters.get_runtime()),
            "--mem",
            str(custom.get("gpu_memory_percent", "99")),
        ]

        if self.gpu_list:
            args += ["--gpu", self.gpu_list]

        # The silent data corruption check runs after the workload and is worth
        # keeping, so it is only dropped when explicitly turned off.
        if not RawConfigParser.BOOLEAN_STATES.get(str(custom.get("verify", "true")).lower(), True):
            args.append("--skip_verify")

        if custom.get("platform"):
            args += ["--platform", str(custom["platform"])]

        return args

    def run_cmd_version(self) -> list[str]:
        return self.engine_module.get_engine().run_cmd_version()

    def parse_version(self, stdout: bytes, _stderr: bytes) -> str:
        return self.engine_module.get_engine().parse_version(stdout, _stderr)

    def empty_result(self):
        """Default empty results for pantheon"""
        return {
            "effective_runtime": 0,
            "skipped": self.skip,
            "score": 0.0,
            "score_unit": "",
            "score_min_gpu": 0.0,
            "pantheon_results": {
                "suite": self.suite,
                "test": self.test,
                "healthy": None,
                "exit_code": None,
                "gpus": {},
            },
        }

    def parse_cmd(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        report = {} if self.skip else self.load_report(stdout, stderr)
        if not report:
            return self.parameters.get_result_format() | self.empty_result()

        gpus = self.build_gpus(report)
        scores = [gpu["score"] for gpu in gpus.values() if gpu["score"] is not None]
        return self.parameters.get_result_format() | {
            "effective_runtime": int(max((gpu["duration"] for gpu in gpus.values()), default=0)),
            "skipped": False,
            # Sum of the performance of every loaded accelerator: the metric
            # that scales with the number of GPUs, hence the one hwgraph plots.
            "score": round(sum(scores), 3),
            "score_unit": self.score_unit(gpus),
            # Worst accelerator of the run: what matters when triaging a server.
            "score_min_gpu": round(min(scores, default=0.0), 3),
            "pantheon_results": {
                "suite": self.suite,
                "test": self.test,
                "version": report.get("pantheon_version"),
                "toolkit_version": report.get("toolkit_version"),
                # pantheon exits 1 when a workload failed or a GPU misbehaved.
                "healthy": self.healthy(gpus),
                "exit_code": self.returncode,
                "gpus": gpus,
            },
        }

    def load_report(self, stdout: bytes, stderr: bytes) -> dict[str, Any]:
        """Load the json report pantheon wrote for this run.

        pantheon does not report on stdout, it writes a report per run and logs
        its path. Following that log line rather than globbing the output
        directory keeps the runs of a job from picking each other's report.
        """
        matches = REPORT_LINE.findall(stdout.decode(errors="replace"))
        if not matches:
            print(f"{self.parameters.get_name_with_position()}: pantheon wrote no report")
            print(f"stdout:\n{stdout.decode(errors='replace')}\nstderr:{stderr.decode(errors='replace')}")
            return {}
        # The last one: a report is written per run, and only the last is complete.
        report = pathlib.Path(self.out_dir) / matches[-1]
        try:
            return json.loads(report.read_bytes())
        except (OSError, json.decoder.JSONDecodeError) as e:
            print(f"{self.parameters.get_name_with_position()}: cannot read the pantheon report {report}: {e}")
            return {}

    def build_gpus(self, report: dict[str, Any]) -> dict[str, Any]:
        """Aggregate the per accelerator metrics out of the pantheon report."""
        identities = {str(gpu.get("id")): gpu for gpu in report.get("gpu_static_info") or []}
        self.check_identities(identities)

        gpus: dict[str, Any] = {}
        for row in report.get("test_results") or []:
            # A suite name in engine_module_parameter would make pantheon run
            # several workloads in a row and report them all: only the one this
            # benchmark asked for belongs in its results.
            if row.get("Test Name") != self.test:
                continue
            index = str(row.get("GPU ID"))
            identity = identities.get(index, {})
            gpu = {
                "name": identity.get("name"),
                "uuid": identity.get("uuid"),
                "manufacturer": identity.get("manufacturer"),
                "duration": number(row.get("Duration (s)")) or 0,
                "status": row.get("Status", "PASS"),
            }
            gpu |= {name: number(row.get(key)) for name, key in GPU_NUMBERS.items()}
            gpu |= {name: text(row.get(key)) for name, key in GPU_STRINGS.items() if text(row.get(key))}
            gpus[index] = gpu
        return gpus

    def check_identities(self, identities: dict[str, dict[str, Any]]) -> None:
        """Warn when pantheon and all-smi do not number the accelerators alike.

        Both enumerate the accelerators on their own, so the 'selected_gpus' directive
        and the GPU_<n> monitoring components only line up as long as the two
        agree. Comparing the uuids turns a silent mismatch into a warning.
        """
        inventory = list_gpus()
        for index, identity in identities.items():
            known = inventory.get(index, {}).get("uuid")
            if identity.get("uuid") and known and identity["uuid"] != known:
                print(
                    f"WARNING: {self.parameters.get_name_with_position()}: pantheon GPU {index} is "
                    f"{identity['uuid']} but all-smi reports {known} at that index: the monitoring "
                    "of this benchmark cannot be matched to its results"
                )

    def score_unit(self, gpus: dict[str, Any]) -> str:
        """Return the unit the workload measured its score in.

        pantheon does not measure the same quantity for every workload: the
        compute ones report TFLOPS and the memory ones GB/s, so the unit is a
        property of the run rather than of the engine.
        """
        units = {gpu["unit"] for gpu in gpus.values() if gpu.get("unit") not in NO_UNIT}
        return units.pop() if len(units) == 1 else ""

    def healthy(self, gpus: dict[str, Any]) -> bool:
        """Return whether every accelerator passed the workload."""
        return self.returncode == 0 and all(gpu["status"] == "PASS" for gpu in gpus.values())
