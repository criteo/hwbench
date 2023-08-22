import pathlib
import json
from unittest.mock import patch
from .stressng import Engine as StressNG


class TestParse(object):
    def test_parsing_stressng(self):
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
            version = test_target.parse_version(ver_stdout, None)
            assert version == (d / "version").read_bytes().strip()

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
