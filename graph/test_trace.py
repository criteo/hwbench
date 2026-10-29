from __future__ import annotations

import itertools
import json
import pickle
from types import SimpleNamespace

import pytest

import graph.trace
from graph.common import cdu_header, location_header
from graph.trace import (
    Bench,
    Trace,
    config_differences,
    context_line,
    gpu_description,
    is_invalid_serial,
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


def test_trace_read_on_first_use(tmp_path):
    """A trace given with --traces is read on its first use, when rendered."""
    path = tmp_path / "results.json"
    path.write_text('{"bench": {}, "hardware": {"dmi": {"serial": "SRV01"}}}')
    trace = Trace(str(path), load=False)
    assert "trace" not in trace.__dict__
    assert trace.get_server_serial() == "SRV01"


def test_content_sent_without(tmp_path):
    """A trace is sent to the workers without its content, read again on the first use of its benchmarks,
    as after being forgotten at the end of a task: its hardware is read without reading it again."""
    path = tmp_path / "results.json"
    path.write_text('{"bench": {}, "hardware": {"dmi": {"serial": "SRV01"}}}')
    trace = Trace(str(path), "srv01")
    sent = pickle.loads(pickle.dumps(trace))
    assert "trace" not in sent.__dict__
    assert sent.get_name() == "srv01"
    assert sent.get_server_serial() == "SRV01"
    assert "trace" not in sent.__dict__
    assert sent.bench_list() == {}
    assert "trace" in sent.__dict__
    trace.forget_content()
    assert "trace" not in trace.__dict__
    assert trace.get_trace() == {"bench": {}, "hardware": {"dmi": {"serial": "SRV01"}}}


def test_invalid_serial(tmp_path, monkeypatch, capsys):
    """A serial made of dots only, the same for every server having it, is replaced by invalid_serial_<N>,
    N counting these servers; a trace read again by a worker keeps its number."""
    monkeypatch.setattr(graph.trace, "INVALID_SERIAL_NUMBERS", itertools.count(1))
    traces = []
    for name, serial, chassis in (("a", "....", "...."), ("b", "SRV01", "CHS01"), ("c", " .. ", "CHS02")):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"hardware": {"dmi": {"serial": serial, "chassis": {"serial": chassis}}}}))
        traces.append(Trace(str(path)))
    assert [t.get_server_serial() for t in traces] == ["invalid_serial_1", "SRV01", "invalid_serial_2"]
    assert [t.get_chassis_serial() for t in traces] == ["invalid_serial_1", "CHS01", "CHS02"]
    out = capsys.readouterr().out
    assert f"{tmp_path / 'a.json'}: invalid chassis serial '....', replaced by invalid_serial_1" in out
    assert f"{tmp_path / 'c.json'}: invalid serial ' .. ', replaced by invalid_serial_2" in out

    sent = pickle.loads(pickle.dumps(traces[2]))
    assert sent.get_server_serial() == "invalid_serial_2"
    traces[0].forget_content()
    assert traces[0].get_server_serial() == "invalid_serial_1"
    # Read again from its conversion in the cache of the output directory, by the main process or a worker
    traces[2].use_cache(tmp_path / "cache")
    assert traces[2].get_trace()["hardware"]["dmi"]["serial"] == "invalid_serial_2"
    worker = pickle.loads(pickle.dumps(traces[2]))
    assert "trace" not in worker.__dict__
    assert worker.get_trace()["hardware"]["dmi"]["serial"] == "invalid_serial_2"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("serial", "invalid"),
    [
        ("", True),
        ("  ", True),
        (None, True),
        ("............", True),
        ("To Be Filled By O.E.M.", True),
        ("TO BE FILLED BY OEM", True),
        ("SRV01", False),
        ("A.B", False),
    ],
)
def test_is_invalid_serial(serial, invalid):
    """A serial left unset is empty, made of dots only, or the classic 'To Be Filled By O.E.M.'."""
    assert is_invalid_serial(serial) is invalid


def test_without_serial_kept(tmp_path, monkeypatch):
    """A DMI without serial nor chassis is kept as is, without consuming a number."""
    monkeypatch.setattr(graph.trace, "INVALID_SERIAL_NUMBERS", itertools.count(1))
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"hardware": {"dmi": {}}}))
    assert Trace(str(path)).get_dmi() == {}
    assert next(graph.trace.INVALID_SERIAL_NUMBERS) == 1


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
        ("SRV01", "host01", "SRV01"),
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


def test_config_differences():
    """Only the jobs and directives that differ, '-' from the reference, '+' from the other job file."""
    reference = {
        "cpu": {"runtime": "120", "engine_module_parameter": "int128,float,matrixprod"},
        "stream": {"runtime": "120"},
        "memrate": {"runtime": "60"},
    }
    config = {
        "cpu": {"runtime": "120", "engine_module_parameter": "int128,fft,matrixprod"},
        "stream": {"runtime": "120", "sync_start": "time"},
        "qsort": {"runtime": "60"},
    }
    assert config_differences(reference, config) == [
        "  [cpu]",
        "- engine_module_parameter=int128,float,matrixprod",
        "+ engine_module_parameter=int128,fft,matrixprod",
        "  [stream]",
        "+ sync_start=time",
        "- [memrate]",
        "+ [qsort]",
    ]
    assert config_differences(reference, reference) == []
