import pathlib

import bench.stressng as stressng


class TestParse(object):
    def test_parsing(self):
        for classname, prefix in [
            (stressng.StressNG, "stressng"),
        ]:
            print(pathlib.Path(".").absolute())
            test_dir = pathlib.Path(f"./tests/parsing/{prefix}")
            test_target = classname("")
            for d in test_dir.iterdir():
                if not d.is_dir():
                    continue
                ver_stdout = open(d / "version-stdout").read()
                ver_stderr = open(d / "version-stderr").read()

                test_target.parse_version(ver_stdout, ver_stderr)

                out_stdout = open(d / "stdout").read()
                out_stderr = open(d / "stderr").read()
                test_target.parse_version(out_stdout, out_stderr)
