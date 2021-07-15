# Copyright 2021 Canonical Ltd.
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

"""Analyze and lint charm structures and files."""

import ast
import os
import pathlib
import shlex
from collections import namedtuple, defaultdict
from typing import List, Generator

from charmcraft import config
from charmcraft.metadata import parse_metadata_yaml

CheckType = namedtuple("CheckType", "attribute lint")(
    attribute="attribute", lint="lint"
)

# result information from each checker/linter
CheckResult = namedtuple("CheckResult", "name result url check_type text")

# generic constant for common results
UNKNOWN = "unknown"
IGNORED = "ignored"
FATAL = "fatal"

# shared state between checkers, to reuse analysis results and/or other intermediate information
shared_state = defaultdict(dict)


class Language:
    """Check the language used to write the charm.

    Currently only Python is detected, if the following checks are true:

    - the charm has a text dispatch with a python call
    - the charm has a `.py` entry point
    - the entry point file is executable
    """

    check_type = CheckType.attribute
    name = "language"
    url = "https://juju.is/docs/sdk/charmcraft-analyze#heading--language"
    text = "The charm is written with Python."

    # different result constants
    Result = namedtuple("Result", "python unknown")(python="python", unknown=UNKNOWN)

    def run(self, basedir: pathlib.Path) -> str:
        """Run the proper verifications."""
        # get the entrypoint from the last useful dispatch line
        dispatch = basedir / "dispatch"
        entrypoint_str = ""
        try:
            with dispatch.open("rt", encoding="utf8") as fh:
                last_line = None
                for line in fh:
                    if line.strip():
                        last_line = line
                if last_line:
                    entrypoint_str = shlex.split(last_line)[-1]
        except (IOError, UnicodeDecodeError):
            return self.Result.unknown

        entrypoint = basedir / entrypoint_str
        if entrypoint.suffix == ".py" and os.access(entrypoint, os.X_OK):
            shared_state[self.name]["entrypoint"] = entrypoint
            return self.Result.python
        return self.Result.unknown


class Framework:
    """Check the framework the charm is based on.

    Currently it detects if the Operator Framework is used, if...

    - the language attribute is set to python
    - the charm contains venv/ops
    - the charm imports ops in the entry point.

    ...or the Reactive Framework is used, if the charm...

    - has a metadata.yaml with "name" in it
    - has a reactive/<name>.py file that imports "charms.reactive"
    - has a file name that starts with "charms.reactive-" inside the "wheelhouse" directory
    """

    check_type = CheckType.attribute
    name = "framework"
    url = "https://juju.is/docs/sdk/charmcraft-analyze#heading--framework"

    # different result constants
    Result = namedtuple("Result", "operator reactive unknown")(
        operator="operator", reactive="reactive", unknown=UNKNOWN
    )

    # different texts to be exposed as `text` (see the property below)
    result_texts = {
        Result.operator: "The charm is based on the Operator Framework.",
        Result.reactive: "The charm is based on the Reactive Framework.",
        Result.unknown: "The charm is not based on any known Framework.",
    }

    def __init__(self):
        self.result = None

    @property
    def text(self):
        """Return a text in function of the result state."""
        if self.result is None:
            raise RuntimeError(
                "Cannot access text before running the Framework checker."
            )
        return self.result_texts[self.result]

    def _get_imports(self, filepath: pathlib.Path) -> Generator[List[str], None, None]:
        """Parse a Python filepath and yield its imports.

        If the file does not exist or cannot be parsed, return empty. Otherwise
        return the name for each imported module, splitted by possible dots.
        """
        if not os.access(filepath, os.R_OK):
            return
        try:
            parsed = ast.parse(filepath.read_bytes())
        except SyntaxError:
            return

        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                for name in node.names:
                    yield name.name.split(".")
            elif isinstance(node, ast.ImportFrom):
                yield node.module.split(".")

    def _check_operator(self, basedir: pathlib.Path) -> bool:
        """Detect if the Operator Framework is used."""
        language_info = shared_state[Language.name]
        if language_info["result"] != Language.Result.python:
            return False

        opsdir = basedir / "venv" / "ops"
        if not opsdir.exists() or not opsdir.is_dir():
            return False

        entrypoint = language_info["entrypoint"]
        for import_parts in self._get_imports(entrypoint):
            if import_parts[0] == "ops":
                return True
        return False

    def _check_reactive(self, basedir: pathlib.Path) -> bool:
        """Detect if the Reactive Framework is used."""
        entrypoint_name = shared_state[JujuMetadata.name]["name"]
        if entrypoint_name is None:
            return False

        wheelhouse_dir = basedir / "wheelhouse"
        if not wheelhouse_dir.exists():
            return False
        if not any(
            f.name.startswith("charms.reactive-") for f in wheelhouse_dir.iterdir()
        ):
            return False

        entrypoint = basedir / "reactive" / f"{entrypoint_name}.py"
        for import_parts in self._get_imports(entrypoint):
            if import_parts[0] == "charms" and import_parts[1] == "reactive":
                return True
        return False

    def run(self, basedir: pathlib.Path) -> str:
        """Run the proper verifications."""
        if self._check_operator(basedir):
            result = self.Result.operator
        elif self._check_reactive(basedir):
            result = self.Result.reactive
        else:
            result = self.Result.unknown
        self.result = result
        return result


class JujuMetadata:
    """Check that the metadata.yaml file exists and is sane.

    The charm is considered to have a valid metadata if the following checks are true:

    - the metadata.yaml is present
    - it is a valid YAML file
    - it has at least the following fields: name, summary, and description
    """

    check_type = CheckType.lint
    name = "metadata"
    url = "https://juju.is/docs/sdk/charmcraft-analyze#heading--metadata"
    text = "Problems found with metadata.yaml file."

    # different result constants
    Result = namedtuple("Result", "ok errors")(ok="ok", errors="errors")

    def run(self, basedir: pathlib.Path) -> str:
        """Run the proper verifications."""
        try:
            metadata = parse_metadata_yaml(basedir)
        except Exception:
            # file not found, corrupted, or mandatory "name" not present
            charm_name = None
            result = self.Result.errors
        else:
            charm_name = metadata.name
            if metadata.summary and metadata.description:
                result = self.Result.ok
            else:
                result = self.Result.errors

        shared_state[self.name]["name"] = charm_name
        return result


# all checkers to run; the order here is important, as some checkers depend on the
# results from others
CHECKERS = [
    Language,
    JujuMetadata,
    Framework,
]


def analyze(config: config.Config, basedir: pathlib.Path) -> List[CheckResult]:
    """Run all checkers and linters."""
    all_results = []
    for cls in CHECKERS:
        # do not run the ignored ones
        if cls.check_type == CheckType.attribute:
            ignore_list = config.analysis.ignore.attributes
        else:
            ignore_list = config.analysis.ignore.linters
        if cls.name in ignore_list:
            all_results.append(
                CheckResult(
                    check_type=cls.check_type,
                    name=cls.name,
                    result=IGNORED,
                    url=None,
                    text=None,
                )
            )
            continue

        checker = cls()
        try:
            result = checker.run(basedir)
        except Exception:
            result = UNKNOWN if checker.check_type == CheckType.attribute else FATAL
        shared_state[checker.name]["result"] = result
        all_results.append(
            CheckResult(
                check_type=checker.check_type,
                name=checker.name,
                url=checker.url,
                text=checker.text,
                result=result,
            )
        )
    return all_results
