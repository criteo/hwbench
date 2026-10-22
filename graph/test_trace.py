import pytest

from graph.trace import Bench, Trace, gpu_description
from hwbench.bench.monitoring_structs import MonitoringContextKeys
from hwbench.utils.archive import create_output_archive


def b200(vbios: str = '"97.00.FA.00.02"', ecc: str = "Enabled", name: str = "NVIDIA B200") -> dict:
    """An accelerator as all-smi inventories it: the VBIOS of older traces keeps its quotes."""
    return {
        "name": name,
        "detail": {
            "CUDA Version": "13.3",
            "Driver Version": "610.57.04",
            "ecc_mode_current": ecc,
            "vbios_version": vbios,
        },
    }


def test_no_gpu():
    assert gpu_description({}) == []


def test_identical_gpus():
    """Everything the accelerators share fits on a single line."""
    gpus = {str(index): b200() for index in range(8)}
    assert gpu_description(gpus) == [
        ("GPU", "8x NVIDIA B200, Driver: 610.57.04, CUDA: 13.3, VBIOS: 97.00.FA.00.02, ECC: enabled"),
    ]


def test_grouped_gpus():
    """A property differing between the accelerators is given per group of GPUs."""
    gpus = {str(index): b200() for index in range(8)}
    gpus["2"] = b200(vbios="97.00.FA.00.01")
    gpus["3"] = b200(vbios="97.00.FA.00.01", ecc="Disabled")
    assert gpu_description(gpus) == [
        ("GPU", "8x NVIDIA B200, Driver: 610.57.04, CUDA: 13.3"),
        ("GPU 0-1, 4-7", "VBIOS: 97.00.FA.00.02, ECC: enabled"),
        ("GPU 2", "VBIOS: 97.00.FA.00.01, ECC: enabled"),
        ("GPU 3", "VBIOS: 97.00.FA.00.01, ECC: disabled"),
    ]


def test_mixed_models():
    """With several models, each group says which one it is."""
    gpus = {"0": b200(), "1": b200(name="NVIDIA H100")}
    assert gpu_description(gpus) == [
        ("GPU", "2 GPUs, Driver: 610.57.04, CUDA: 13.3, VBIOS: 97.00.FA.00.02, ECC: enabled"),
        ("GPU 0", "NVIDIA B200"),
        ("GPU 1", "NVIDIA H100"),
    ]


def test_load_compressed_output_directory(tmp_path):
    """A trace is read from the results.json of a compressed output directory of hwbench."""
    out_dir = tmp_path / "hwbench-out-1"
    out_dir.mkdir()
    (out_dir / "results.json").write_text('{"bench": {}}')
    archive = create_output_archive(out_dir, "serial", "1")
    assert Trace(str(archive)).get_trace() == {"bench": {}}

    (out_dir / "results.json").unlink()
    archive = create_output_archive(out_dir, "serial", "2")
    with pytest.raises(ValueError, match="does not contain a results.json"):
        Trace(str(archive))


class RamTrace:
    """A trace whose processor meters its memory, with the given samples of ram power."""

    def __init__(self, ram: list[float]):
        self.ram = ram

    def get_trace(self) -> dict:
        def power(name: str, values: list[float]) -> dict:
            return {"name": name, "unit": "Watts", "mean": values, "min": values, "max": values}

        cpu = {"package": power("package", [150.0, 160.0]), "Ram": power("Ram", self.ram)}
        monitoring = {
            "metadata": {"samples_count": 2, "iteration_time": 10},
            "contexts": {"PowerConsumption": {"CPU": cpu}},
        }
        return {"bench": {"job_0": {"monitoring": monitoring}}}


@pytest.mark.parametrize(
    ("ram", "expected"),
    [
        ([20.0, 21.0], ["Ram", "package"]),
        ([20.0], ["package"]),
        ([], ["package"]),
    ],
)
def test_incomplete_ram(ram, expected, capsys):
    """The memory power is optional: missing samples silently drop it instead of stopping the graphs."""
    bench = Bench(RamTrace(ram), "job_0")
    cpu = bench.load_monitoring()[MonitoringContextKeys.PowerConsumption]["CPU"]
    assert sorted(cpu) == expected
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("serial", "nodename", "expected"),
    [
        ("CZ2D2N08V8", "host01", "CZ2D2N08V8"),
        (None, "host01", "host01"),
        ("  ", "host01", "host01"),
    ],
)
def test_default_logical_name(serial, nodename, expected):
    """A trace given without logical_name is named after the server serial, or its hostname without one."""
    trace = Trace.__new__(Trace)
    trace.trace = {"hardware": {"dmi": {"serial": serial}}, "environment": {"kernel": {"nodename": nodename}}}
    assert trace.default_logical_name() == expected


def test_default_logical_name_missing():
    """Without serial number nor hostname, the trace must be given a logical_name."""
    trace = Trace.__new__(Trace)
    trace.filename = "results.json"
    trace.trace = {"hardware": {"dmi": {"serial": None}}, "environment": {}}
    with pytest.raises(SystemExit):
        trace.default_logical_name()
