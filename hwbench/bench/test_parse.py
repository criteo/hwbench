import pathlib
import json

from . import stressng


class TestParse(object):
    def test_parsing(self):
        for classname, prefix in [
            (stressng.StressNGQsort, "stressng"),
        ]:
            test_dir = pathlib.Path(f"./tests/parsing/{prefix}")
            for d in test_dir.iterdir():
                print(f"parsing test {d.name}")
                test_target = classname(pathlib.Path(""), 0, 0)
                if not d.is_dir():
                    continue
                ver_stdout = (d / "version-stdout").read_bytes()
                ver_stderr = (d / "version-stderr").read_bytes()

                version = test_target.parse_version(ver_stdout, ver_stderr)
                assert version == (d / "version").read_bytes().strip()

                stdout = (d / "stdout").read_bytes()
                stderr = (d / "stderr").read_bytes()

                output = test_target.parse_cmd(stdout, stderr)
                # these are unused in parsing
                del output["timeout"]
                del output["workers"]
                assert output == json.loads((d / "output").read_bytes())

    def test_methods(self):
        test_dir = pathlib.Path("./tests/parsing/stressngmethods")
        for d in test_dir.iterdir():
            if not d.is_dir():
                continue
            print(f"parsing methods test {d.name}")
            test_target = stressng.StressNGMethods(pathlib.Path(""), 0, 0)

            stdout = (d / "stdout").read_bytes()
            stderr = (d / "stderr").read_bytes()

            output = test_target.parse_cmd(stdout, stderr)
            assert output == json.loads((d / "output").read_bytes())
