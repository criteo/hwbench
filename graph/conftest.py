from __future__ import annotations

import os
import pathlib

import pytest
from matplotlib.figure import Figure


def pytest_configure(config):
    config.addinivalue_line("markers", "render: render the images for real, instead of an empty file per image")


@pytest.fixture(autouse=True)
def no_image(request, monkeypatch):
    """The tests check which graphs are made, not their pixels: an image is an empty file at its path.

    Drawing and encoding the images was most of the time of the suite, and filled the temporary directory.
    """
    if request.node.get_closest_marker("render"):
        return

    def savefig(self, fname, *args, **kwargs):
        if isinstance(fname, (str, os.PathLike)):
            pathlib.Path(fname).touch()

    monkeypatch.setattr(Figure, "savefig", savefig)
