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
