from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph.common import location_header
from graph.trace import Bench, Trace, context_line, gpu_description, shared_location_line
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


def context_trace(name: str, context: str | None) -> Trace:
    trace = Trace.__new__(Trace)
    trace.logical_name = name
    trace.trace = {"context": context} if context is not None else {}
    return trace


def test_context_line():
    """The traces sharing a context give it once, different contexts give the context of each."""
    assert context_line([context_trace("SRV01", "bios-v2"), context_trace("SRV02", "bios-v2")]) == "Context: bios-v2"
    assert (
        context_line([context_trace("SRV01", "bios-v1"), context_trace("SRV02", "bios-v2")])
        == "Contexts: SRV01: bios-v1, SRV02: bios-v2"
    )
    assert context_line([context_trace("SRV01", "bios-v2"), context_trace("SRV02", None)]) == "Contexts: SRV01: bios-v2"
    assert context_line([context_trace("SRV01", None), context_trace("SRV02", "")]) is None


LOCATION = {"Country": "FR", "Datacenter": "PA99", "Datahall": "DH2", "Room": "Cage 1", "Rack": "A12", "U": "23"}


def located_trace(location: dict | None) -> Trace:
    """A trace of a server, located or not."""
    trace = Trace.__new__(Trace)
    trace.logical_name = "SRV01"
    trace.trace = {
        "hardware": {
            "dmi": {"serial": "SRV01", "product": "ProLiant DL385 Gen11", "bios": {"version": "3.16"}},
            "cpu": {"model": "AMD EPYC 9124", "sockets": 2, "physical_cores": 32, "numa_domains": 8},
        },
        "environment": {"kernel": {"release": "6.18.52"}},
        "bench": {"cpu_0": {}},
    }
    if location is not None:
        trace.trace["location"] = location
    return trace


def test_location():
    """The location of the server, in one line under the System line of the headers."""
    trace = located_trace(LOCATION)
    assert trace.get_location() == LOCATION
    assert trace.get_location_line() == "FR / PA99 / DH2 / Cage 1 / Rack A12 / U23"
    assert Bench(trace, "cpu_0").get_system_title().splitlines()[:2] == [
        "System:SRV01 ProLiant DL385 Gen11 Bios:v3.16 Linux Kernel:6.18.52",
        "Location: FR / PA99 / DH2 / Cage 1 / Rack A12 / U23",
    ]


@pytest.mark.parametrize("location", [None, {}])
def test_without_location(location):
    """A trace without location has no Location line."""
    trace = located_trace(location)
    assert trace.get_location() == {}
    assert trace.get_location_line() is None
    assert "Location" not in Bench(trace, "cpu_0").get_system_title()


def test_shared_location_line():
    """The servers of a same rack share its location, whatever their height."""
    traces = [located_trace(LOCATION), located_trace(LOCATION | {"U": "24"})]
    assert shared_location_line(traces) == "Location: FR / PA99 / DH2 / Cage 1 / Rack A12"
    assert location_header(SimpleNamespace(location=shared_location_line(traces))) == (
        "\nLocation: FR / PA99 / DH2 / Cage 1 / Rack A12"
    )
    lab = LOCATION | {"Extra": "Secret Lab 1"}
    assert shared_location_line([located_trace(LOCATION), located_trace(lab)]) == (
        "Location: FR / PA99 / DH2 / Cage 1 / Rack A12"
    )


@pytest.mark.parametrize(
    "other",
    [LOCATION | {"Rack": "A13"}, {"Rack": "A12", "U": "24"}, None],
)
def test_no_shared_location_line(other):
    """A location differing up to the rack, or missing, is not shared."""
    assert shared_location_line([located_trace(LOCATION), located_trace(other)]) is None
    assert location_header(SimpleNamespace(location=None)) == ""


@pytest.mark.parametrize("fine", [{"U": "23"}, {"U": "23", "Extra": "Secret Lab 1"}])
def test_fine_location_alone_is_not_shared(fine):
    """The height in the rack, even with Extra, says nothing of the place the servers share."""
    assert shared_location_line([located_trace(fine), located_trace(fine)]) is None


def test_extra_alone_is_shared():
    """Extra set alone is the place the servers share."""
    lab = located_trace({"Extra": "Secret Lab 1"})
    assert shared_location_line([lab, lab]) == "Location: Secret Lab 1"
    assert shared_location_line([lab, located_trace({"Extra": "Secret Lab 2"})]) is None
