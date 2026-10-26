from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph.common import cdu_header, location_header
from graph.trace import (
    Bench,
    Trace,
    context_line,
    gpu_description,
    own_location,
    shared_cdu_lines,
    shared_location,
    shared_location_line,
)
from hwbench.bench.monitoring_structs import MonitoringContextKeys
from hwbench.environment.environment_file import Location
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


LEVELS = ["Country", "Datacenter", "Datahall", "Room", "Rack", "Position"]
PATH = ["FR", "PA99", "2", "1", "A12", "23"]
LOCATION = {"path": PATH, "separator": "/", "levels": LEVELS}


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


def at(*path: str) -> dict:
    """A location of these places, without levels."""
    return {"path": list(path), "separator": "/"}


def test_location():
    """The location of the server, in one line under the System line of the headers."""
    trace = located_trace(LOCATION)
    assert trace.get_location() == Location(PATH, "/", LEVELS)
    assert trace.get_location_line() == "Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23"
    assert Bench(trace, "cpu_0").get_system_title().splitlines()[:2] == [
        "System:SRV01 ProLiant DL385 Gen11 Bios:v3.16 Linux Kernel:6.18.52",
        "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23",
    ]


@pytest.mark.parametrize("location", [None, {}, at()])
def test_without_location(location):
    """A trace without location has no Location line."""
    trace = located_trace(location)
    assert trace.get_location() is None
    assert trace.get_location_line() is None
    assert "Location" not in Bench(trace, "cpu_0").get_system_title()


def test_shared_location_line():
    """The servers of a same rack share its location, whatever their height."""
    traces = [located_trace(LOCATION), located_trace(LOCATION | {"path": [*PATH[:-1], "24"]})]
    assert shared_location(traces) == Location(PATH[:-1], "/", LEVELS[:-1])
    assert shared_location_line(traces) == "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12"
    assert location_header(SimpleNamespace(location=shared_location_line(traces))) == (
        "\nLocation: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12"
    )
    assert own_location(traces[1], shared_location(traces)) == Location(["24"], "/", ["Position"])


def test_shared_location_of_the_same_place():
    """The nodes of a chassis share its whole location, and have none of their own."""
    traces = [located_trace(LOCATION), located_trace(LOCATION)]
    assert (
        shared_location_line(traces)
        == "Location: Country FR / Datacenter PA99 / Datahall 2 / Room 1 / Rack A12 / Position 23"
    )
    assert own_location(traces[0], shared_location(traces)) is None
    lab = located_trace(at("Secret Lab 1"))
    assert shared_location_line([lab, lab]) == "Location: Secret Lab 1"


def test_shared_location_without_levels():
    """The places are shared whatever their levels, known only when all the servers give the same."""
    traces = [located_trace(LOCATION), located_trace(at("FR", "PA99", "3"))]
    assert shared_location(traces) == Location(["FR", "PA99"])
    other_levels = LOCATION | {"levels": ["Country", "DC", "DH", "Room", "Rack", "Position"]}
    assert shared_location([located_trace(LOCATION), located_trace(other_levels)]) == Location(PATH)


def test_shared_location_with_a_separator():
    """The shared location is shown with the separator of the servers."""
    traces = [located_trace({"path": ["PA3", "A12", "1"], "separator": ","}), located_trace(at("PA3", "A12", "2"))]
    assert shared_location_line(traces) == "Location: PA3 , A12"


@pytest.mark.parametrize(
    "other",
    [at("DE", "FRA1", "2"), at("Secret Lab 1"), at("", "PA99", "2"), None],
)
def test_no_shared_location_line(other):
    """A location differing from the widest place, or missing, is not shared."""
    assert shared_location_line([located_trace(LOCATION), located_trace(other)]) is None
    assert location_header(SimpleNamespace(location=None)) == ""


def test_unknown_places_are_not_shared():
    """Places not known, shared by all the servers, are not a location."""
    assert shared_location_line([located_trace(at("", "", "A12")), located_trace(at("", "", "A13"))]) is None


CDU = {"type": "CDU", "vendor": "HPE", "model": "MCDU-4U-FR-2", "protocol": "SNMP_V2C", "driver": "HPEMCDU4UFR2"}


def cooled_trace(**cdus) -> Trace:
    """A trace of a server monitored with these CDUs, by section."""
    trace = located_trace(None)
    trace.trace["hardware"]["cdu"] = cdus
    return trace


def test_cdu_lines():
    """Each CDU gives its section, vendor, model and protocol, then its firmware and serial only when known."""
    known = {"firmware_version": "2.1.2", "serial_number": "CZ1234", "url": "snmp://cdu.example.net:161"}
    trace = cooled_trace(CDU_cooling=CDU, CDU_2=CDU | known)
    assert trace.get_cdu_lines() == [
        "CDU_cooling HPE MCDU-4U-FR-2 SNMP_V2C",
        "CDU_2 HPE MCDU-4U-FR-2 SNMP_V2C FW:2.1.2 SN:CZ1234 (cdu.example.net)",
    ]
    # Before the System line, so that it does not split the description of the host
    assert Bench(trace, "cpu_0").get_system_title().splitlines()[:3] == [
        "CDU: CDU_cooling HPE MCDU-4U-FR-2 SNMP_V2C",
        "CDU: CDU_2 HPE MCDU-4U-FR-2 SNMP_V2C FW:2.1.2 SN:CZ1234 (cdu.example.net)",
        "System:SRV01 ProLiant DL385 Gen11 Bios:v3.16 Linux Kernel:6.18.52",
    ]
    assert located_trace(None).get_cdu_lines() == []
    assert "CDU" not in Bench(located_trace(None), "cpu_0").get_system_title()


def test_shared_cdu_lines():
    """The servers monitored with the same CDUs give them in the header of their graphs, else nothing."""
    cooled = [cooled_trace(CDU_cooling=CDU), cooled_trace(CDU_cooling=CDU)]
    assert shared_cdu_lines(cooled) == ["CDU_cooling HPE MCDU-4U-FR-2 SNMP_V2C"]
    assert cdu_header(SimpleNamespace(cdus=shared_cdu_lines(cooled))) == "\nCDU: CDU_cooling HPE MCDU-4U-FR-2 SNMP_V2C"
    assert shared_cdu_lines([cooled[0], located_trace(None)]) == []
    assert shared_cdu_lines([located_trace(None), located_trace(None)]) == []
    assert cdu_header(SimpleNamespace()) == ""
