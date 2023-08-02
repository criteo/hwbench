import pathlib
import json

import bench.stressng as stressng


class TestParse(object):
    def test_parsing(self):
        for classname, prefix in [
            (stressng.StressNG, "stressng"),
        ]:
            test_dir = pathlib.Path(f"./tests/parsing/{prefix}")
            for d in test_dir.iterdir():
                print(f"parsing test {d.name}")
                test_target = classname("")
                if not d.is_dir():
                    continue
                ver_stdout = (d / "version-stdout").read_text()
                ver_stderr = (d / "version-stderr").read_text()

                version = test_target.parse_version(ver_stdout, ver_stderr)
                assert version == (d / "version").read_text().strip()

                stdout = (d / "stdout").read_text()
                stderr = (d / "stderr").read_text()

                output = test_target.parse_cmd(stdout, stderr)
                assert output == json.loads((d / "output").read_text())
