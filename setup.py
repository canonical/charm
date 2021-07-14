#!/usr/bin/env python3

# Copyright 2020-2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

"""Setup script for Charmcraft."""

from pathlib import Path
from textwrap import dedent
from setuptools import setup

import charmcraft


with open("README.md", "rt", encoding="utf8") as fh:
    long_description = fh.read()

install_requires = [
    "appdirs",
    "attrs",
    "craft-providers",
    "craft-parts @ https://github.com/canonical/craft-parts/archive/refs/tags/v1.0-alpha.tar.gz",
    "humanize>=2.6.0",
    "jsonschema",
    "jinja2",
    "macaroonbakery",
    "pydantic",
    "python-dateutil",
    "pyyaml",
    "requests",
    "requests-toolbelt",
    "requests-unixsocket",
    "tabulate",
]

try:
    os_release = open("/etc/os-release").read()
    ubuntu = "ID=ubuntu" in os_release
except FileNotFoundError:
    ubuntu = False

if ubuntu:
    install_requires += [
        "python-apt",
    ]

dev_requires = [
    "black",
    "coverage",
    "flake8",
    "ops>=0.8.0",
    "pydocstyle",
    "pytest",
    "responses",
]

extras_require = {
    "dev": dev_requires,
}

version_path = Path("charmcraft/version.py")
version_backup = Path("charmcraft/version.py~")
version_path.rename(version_backup)
try:
    with version_path.open("wt", encoding="utf8") as fh:
        fh.write(
            dedent(
                """
            # this is a generated file

            version = {!r}
            """
            ).format(charmcraft.__version__)
        )

    setup(
        name="charmcraft",
        version=charmcraft.__version__,
        author="Facundo Batista",
        author_email="facundo.batista@canonical.com",
        description="The main tool to build, upload, and develop in general the Juju charms.",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/canonical/charmcraft",
        license="Apache-2.0",
        packages=["charmcraft", "charmcraft.commands", "charmcraft.commands.store"],
        classifiers=[
            "Environment :: Console",
            "License :: OSI Approved :: Apache Software License",
            "Operating System :: OS Independent",
            "Programming Language :: Python :: 3",
        ],
        entry_points={
            "console_scripts": ["charmcraft = charmcraft.main:main"],
        },
        python_requires=">=3",
        install_requires=install_requires,
        extras_require=extras_require,
        include_package_data=True,  # so we get templates in the wheel
    )

finally:
    version_backup.rename(version_path)
