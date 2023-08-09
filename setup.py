#!/usr/bin/env python3

import os
import setuptools


basedir = os.path.dirname(__file__)


def read_requirements(path):
    with open(os.path.join(basedir, path)) as f:
        lines = [x.strip() for x in f.readlines()]
        return [x for x in lines if x[0] != "#"]


meta = {}
meta["requirements"] = read_requirements("requirements/base.txt")
meta["install_requires"] = [line for line in meta["requirements"] if "://" not in line]


setuptools.setup(
    name="hwbench",
    version="0.0.1",
    install_requires=meta["install_requires"],
    python_requires="~=3.9",
    dependency_links=[],
    data_files=[(".", ["requirements/base.txt"])],
    entry_points={
        "console_scripts": [
            "hwbench =  hwbench.hwbench:main",
        ],
    },
    packages=setuptools.find_packages(),
)
