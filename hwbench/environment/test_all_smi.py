import json
import pathlib
import unittest

from .all_smi import AllSMI, parse_version

TEST_DIR = pathlib.Path("./hwbench/tests/parsing/all-smi")
# The 3 H100 of the fixture: two loaded, one idle.
H100 = TEST_DIR / "v0263-h100" / "stdout"


class TestAllSMI(unittest.TestCase):
    def test_parsing(self):
        for d in TEST_DIR.iterdir():
            if not d.is_dir():
                continue

            with self.subTest(f"all-smi dir {d}"):
                test_target = AllSMI(d)

                version = test_target.parse_version((d / "version-stdout").read_bytes(), b"")
                assert version == (d / "version").read_text().strip()

                output = test_target.parse_cmd((d / "stdout").read_bytes(), (d / "stderr").read_bytes())
                assert output == json.loads((d / "output").read_bytes())

    def test_no_output(self):
        """all-smi writes nothing when the host has no accelerator."""
        assert AllSMI(pathlib.Path("")).parse_cmd(b"", b"") == {}

    def test_unsupported_schema(self):
        """A schema we do not know must report no accelerator, not a wrong one."""
        frame = {"schema": 2, "gpus": [{"uuid": "GPU-0"}]}
        assert AllSMI(pathlib.Path("")).parse_cmd(json.dumps(frame).encode(), b"") == {}

    def test_vendor_detail_is_kept_verbatim(self):
        """The vendor properties are reported as all-smi named them."""
        gpus = AllSMI(pathlib.Path("")).parse_cmd(H100.read_bytes(), b"")
        assert gpus["0"]["detail"]["Driver Version"] == "580.65.06"
        assert gpus["0"]["detail"]["power_limit_current"] == "700.00"

    def test_vendor_detail_is_unquoted(self):
        """The NVIDIA backend keeps the quotes nvidia-smi prints around the VBIOS version."""
        frame = {"schema": 1, "gpus": [{"uuid": "GPU-0", "detail": {"vbios_version": '"97.00.FA.00.02"'}}]}
        gpus = AllSMI(pathlib.Path("")).parse_cmd(json.dumps(frame).encode(), b"")
        assert gpus["0"]["detail"]["vbios_version"] == "97.00.FA.00.02"

    def test_version(self):
        assert parse_version(b"all-smi 0.26.3\n") == "0.26.3"
