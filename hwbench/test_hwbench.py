from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hwbench.hwbench import format_output, parse_options


def output(context: str | None) -> dict:
    config = MagicMock()
    config.to_dict.return_value = {}
    return format_output({}, {}, {}, config, context)


def test_context():
    """The context of the run is kept in results.json, stripped."""
    assert output("  bios-v2 ")["context"] == "bios-v2"


@pytest.mark.parametrize("context", [None, "", "   "])
def test_without_context(context):
    """The context is optional: without it, results.json has no context."""
    assert "context" not in output(context)


def test_context_option():
    with patch("sys.argv", ["hwbench", "-j", "jobs.conf", "--context", "new thermal paste"]):
        assert parse_options().context == "new thermal paste"
    with patch("sys.argv", ["hwbench", "-j", "jobs.conf"]):
        assert parse_options().context is None


def test_environment_option():
    with patch("sys.argv", ["hwbench", "-j", "jobs.conf", "-e", "environment.cfg"]):
        assert parse_options().environment == "environment.cfg"
    with patch("sys.argv", ["hwbench", "-j", "jobs.conf"]):
        assert parse_options().environment is None


@pytest.mark.parametrize("option", ["-m", "--monitoring-config"])
def test_replaced_monitoring_config_option(option, capsys):
    """-m/--monitoring-config stops hwbench with the option replacing it."""
    with patch("sys.argv", ["hwbench", "-j", "jobs.conf", option, "monitoring.cfg"]), pytest.raises(SystemExit):
        parse_options()
    assert f"{option} is replaced by -e/--environment" in capsys.readouterr().err
