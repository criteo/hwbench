import pathlib
import json
import unittest
from unittest.mock import patch

from ..bench.benchmarks import BenchmarkParameters
from .stressng import Engine as StressNG
from .stressng import (
    StressNGQsort,
    EngineModuleQsort,
)


class TestParse(unittest.TestCase):
    def test_engine_parsing_version(self):
        test_dir = pathlib.Path("./tests/parsing/stressng")
        for d in test_dir.iterdir():
            # We need to patch list_module_parameters() function
            # to avoid considering the local stress-ng binary
            with patch(
                "hwbench.engines.stressng.EngineModuleCpu.list_module_parameters"
            ) as p:
                p.return_value = (
                    pathlib.Path("./tests/parsing/stressngmethods/v16/stdout")
                    .read_bytes()
                    .split(b":", 1)
                )
                test_target = StressNG()
            if not d.is_dir():
                continue
            ver_stdout = (d / "version-stdout").read_bytes()
            ver_stderr = (d / "version-stderr").read_bytes()
            version = test_target.parse_version(ver_stdout, ver_stderr)
            assert version == (d / "version").read_bytes().strip()

    def test_module_parsing_output(self):
        engine = None
        # We need to patch list_module_parameters() function
        # to avoid considering the local stress-ng binary
        with patch(
            "hwbench.engines.stressng.EngineModuleCpu.list_module_parameters"
        ) as p:
            p.return_value = (
                pathlib.Path("./tests/parsing/stressngmethods/v16/stdout")
                .read_bytes()
                .split(b":", 1)
            )
            engine = StressNG()
        for classname, engine_module, prefix in [
            (StressNGQsort, EngineModuleQsort, "stressng"),
        ]:
            test_dir = pathlib.Path(f"./tests/parsing/{prefix}")
            for d in test_dir.iterdir():
                if not d.is_dir():
                    continue

                with self.subTest(f"prefix {prefix} dir {d}"):
                    # Mock elements
                    path = pathlib.Path("")
                    params = BenchmarkParameters(path, prefix, 0, "", 0, "")
                    module = engine_module(engine, prefix)

                    # Class to test parse_cmd
                    test_target = classname(module, params)

                    # Populate version
                    ver_stdout = (d / "version-stdout").read_bytes()
                    test_target.parse_version(ver_stdout, None)

                    # Output of command to parse
                    stdout = (d / "stdout").read_bytes()
                    stderr = (d / "stderr").read_bytes()
                    output = test_target.parse_cmd(stdout, stderr)
                    # these are unused in parsing
                    for key in test_target.parameters.get_result_format().keys():
                        output.pop(key, None)
                    assert output == json.loads((d / "output").read_bytes())

    def test_stressng_methods(self):
        test_dir = pathlib.Path("./tests/parsing/stressngmethods")
        for d in test_dir.iterdir():
            if not d.is_dir():
                continue

            print(f"parsing methods test {d.name}")
            # We need to patch list_module_parameters() function
            # to avoid considering the local stress-ng binary
            with patch(
                "hwbench.engines.stressng.EngineModuleCpu.list_module_parameters"
            ) as p:
                p.return_value = p.return_value = (
                    pathlib.Path("./tests/parsing/stressngmethods/v16/stdout")
                    .read_bytes()
                    .split(b":", 1)
                )
                test_target = StressNG().get_module("cpu")

            output = test_target.get_module_parameters()
            assert output == json.loads((d / "output").read_bytes())
