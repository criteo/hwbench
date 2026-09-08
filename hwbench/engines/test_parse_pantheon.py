from __future__ import annotations

import json
import pathlib
import subprocess
import unittest
from unittest.mock import patch

import pytest

from hwbench.bench.parameters import BenchmarkParameters
from hwbench.environment.mock import MockHardware
from hwbench.utils.helpers import versiontuple

from .pantheon import Engine as PantheonEngine
from .pantheon import EngineModuleSuite, Pantheon

TEST_DIR = pathlib.Path("./hwbench/tests/parsing/pantheon")

# The accelerators of the fixture, as all-smi inventoried them.
INVENTORY = {
    str(index): {
        "index": index,
        "uuid": f"GPU-1a2b3c4d-0000-0000-0000-00000000000{index}",
        "name": "NVIDIA H100 80GB HBM3",
        "device_type": "GPU",
    }
    for index in range(3)
}


def mock_engine() -> PantheonEngine:
    with patch("hwbench.utils.helpers.is_binary_available") as iba:
        iba.return_value = True
        engine = PantheonEngine()
        engine.init()
        return engine


def mock_parameters(
    test: str = "tensor_virus",
    gpu_list: str = "0,1,2",
    out_dir: pathlib.Path | None = None,
) -> BenchmarkParameters:
    gpus = [int(gpu) for gpu in gpu_list.split(",") if gpu]
    return BenchmarkParameters(
        out_dir if out_dir is not None else pathlib.Path(""),
        "pantheon",
        3,
        "",
        30,
        test,
        "",
        MockHardware(),
        "none",
        None,  # type: ignore[arg-type] # this bench does not monitor
        "bypass",
        "none",
        pinned_gpus=gpus,
    )


def mock_target(
    test: str = "tensor_virus",
    gpu_list: str = "0,1,2",
    suite: str = "core",
    out_dir: pathlib.Path | None = None,
) -> Pantheon:
    engine = mock_engine()
    return Pantheon(EngineModuleSuite(engine, suite), mock_parameters(test, gpu_list, out_dir))


class TestParse(unittest.TestCase):
    def test_engine_parsing_version(self):
        for d in TEST_DIR.iterdir():
            if not d.is_dir():
                continue
            test_target = mock_engine()
            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()
            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_text().strip()
            assert versiontuple(test_target.get_version()) >= versiontuple("1.2.0")

    def requirements(self, version: bytes) -> list[str]:
        """Return the requirements a pantheon printing <version> does not meet."""
        engine = mock_engine()
        with (
            patch("hwbench.bench.engine.is_binary_available", return_value=True),
            patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, version, b"")),
        ):
            return [str(problem) for problem in engine.check_requirements()]

    def test_too_old_binary_stops_the_run(self):
        """An older pantheon has neither the json report nor --gpu: nothing must run."""
        assert self.requirements(b"pantheon 1.1.0\n") == ["Binary pantheon 1.1.0 is too old, expecting >= 1.2.0"]
        assert self.requirements(b"pantheon 1.2.0\n") == []

    def test_prerelease_version(self):
        """A pre-release suffix must not defeat the version comparison."""
        assert self.requirements(b"pantheon 1.3.0-rc1\n") == []

    def test_unparsable_version(self):
        assert self.requirements(b"pantheon unknown\n") == ["Binary pantheon unknown is too old, expecting >= 1.2.0"]
        assert self.requirements(b"") == ["Binary pantheon (unknown release) is too old, expecting >= 1.2.0"]

    def test_module_parsing_output(self):
        for d in TEST_DIR.iterdir():
            if not d.is_dir():
                continue

            with self.subTest(f"pantheon dir {d}"):
                test_target = mock_target(out_dir=d)
                test_target.parse_version((d / "version-stdout").read_bytes(), b"")
                # pantheon exits 1 when a workload failed: that is a result to
                # record, not a failure to parse.
                test_target.returncode = 1

                with patch("hwbench.engines.pantheon.list_gpus", return_value=INVENTORY):
                    output = test_target.parse_cmd((d / "stdout").read_bytes(), (d / "stderr").read_bytes())
                for key in test_target.parameters.get_result_format():
                    output.pop(key, None)
                assert output == json.loads((d / "output").read_bytes())

    def test_score_is_the_sum_of_the_accelerators(self):
        d = TEST_DIR / "v120"
        test_target = mock_target(out_dir=d)
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        test_target.returncode = 1
        with patch("hwbench.engines.pantheon.list_gpus", return_value=INVENTORY):
            output = test_target.parse_cmd((d / "stdout").read_bytes(), b"")

        gpus = output["pantheon_results"]["gpus"]
        assert output["score"] == round(989.512 + 812.338 + 0.0, 3)
        # The unit is a property of the workload, not of the engine.
        assert output["score_unit"] == "TFLOPS"
        # The card whose workload never started is the worst of the server.
        assert output["score_min_gpu"] == 0.0
        assert not output["pantheon_results"]["healthy"]
        # 'N/A' is a missing sensor, not a value.
        assert gpus["2"]["power_avg_watts"] is None
        assert gpus["2"]["failure_reason"] == "CUDA error: out of memory"
        # A card that was not throttled reports no reason rather than 'N/A'.
        assert "throttle_reason" not in gpus["0"]
        assert gpus["1"]["throttle_reason"] == "SwThermalSlowdown"

    def test_only_the_requested_workload_is_reported(self):
        """A report holding several workloads must not mix them up."""
        d = TEST_DIR / "v120"
        test_target = mock_target(test="fp64_virus", out_dir=d)
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        test_target.returncode = 0
        with patch("hwbench.engines.pantheon.list_gpus", return_value=INVENTORY):
            output = test_target.parse_cmd((d / "stdout").read_bytes(), b"")
        assert output["pantheon_results"]["gpus"] == {}
        assert output["score"] == 0.0

    def test_mismatched_inventory_is_reported(self):
        """The GPU ids of pantheon and of all-smi must describe the same cards."""
        d = TEST_DIR / "v120"
        test_target = mock_target(out_dir=d)
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        shifted = {"0": {"index": 0, "uuid": "GPU-somewhere-else"}}
        with (
            patch("hwbench.engines.pantheon.list_gpus", return_value=shifted),
            patch("builtins.print") as printed,
        ):
            test_target.parse_cmd((d / "stdout").read_bytes(), b"")
        warnings = [call for call in printed.call_args_list if "WARNING" in str(call)]
        assert len(warnings) == 1
        assert "cannot be matched" in str(warnings[0])

    def test_run_cmd(self):
        test_target = mock_target(test="fp64_virus", gpu_list="0,1,4")
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        assert test_target.run_cmd() == [
            "pantheon",
            "--test",
            "fp64_virus",
            "--duration",
            "30",
            "--mem",
            "99",
            "--gpu",
            "0,1,4",
        ]

    def test_run_cmd_custom_parameters(self):
        engine = mock_engine()
        params = mock_parameters()
        params.custom_parameters |= {
            "gpu_memory_percent": "40",
            "verify": "false",
            "platform": "hip",
        }
        test_target = Pantheon(EngineModuleSuite(engine, "core"), params)
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        assert test_target.run_cmd() == [
            "pantheon",
            "--test",
            "tensor_virus",
            "--duration",
            "30",
            "--mem",
            "40",
            "--gpu",
            "0,1,2",
            "--skip_verify",
            "--platform",
            "hip",
        ]

    def test_output_without_report(self):
        """A run that wrote no report must give an empty result."""
        test_target = mock_target()
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        output = test_target.parse_cmd(b"Error: No compiler found.\n", b"")
        assert output["score"] == 0.0
        assert output["pantheon_results"]["gpus"] == {}

    def test_unreadable_report(self):
        """A report that vanished must be reported, not raise."""
        test_target = mock_target()
        test_target.parse_version(b"pantheon 1.2.0\n", b"")
        output = test_target.parse_cmd(b"[PANTHEON] Snapshot saved to: database/gone.json\n", b"")
        assert output["score"] == 0.0

    def test_unknown_test(self):
        with pytest.raises(LookupError):
            mock_target(test="cpu_virus")

    def test_test_of_another_suite(self):
        """A workload of another suite does not belong to this module."""
        with pytest.raises(LookupError):
            mock_target(test="memory_read", suite="core")
