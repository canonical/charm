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

"""Tests for analyze and lint code."""

from unittest.mock import patch

import pytest

from charmcraft.linters import (
    CHECKERS,
    CheckType,
    FATAL,
    Framework,
    IGNORED,
    JujuMetadata,
    Language,
    UNKNOWN,
    analyze,
    shared_state,
)


EXAMPLE_DISPATCH = """
#!/bin/sh

PYTHONPATH=lib:venv ./charm.py
"""

# --- tests for Language checker


def test_language_python(tmp_path):
    """The charm is written in Python."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_text(EXAMPLE_DISPATCH)
    entrypoint = tmp_path / "charm.py"
    entrypoint.touch()
    entrypoint.chmod(0o700)
    result = Language().run(tmp_path)
    assert result == Language.Result.python


def test_language_no_dispatch(tmp_path):
    """The charm has no dispatch at all."""
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_inaccessible_dispatch(tmp_path):
    """The charm has a dispatch we can't use."""
    dispatch = tmp_path / "dispatch"
    dispatch.touch()
    dispatch.chmod(0o000)
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_broken_dispatch(tmp_path):
    """The charm has a dispatch which we can't decode."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_bytes(b"\xC0\xC0")
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_empty_dispatch(tmp_path):
    """The charm dispatch is empty."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_text("")
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_no_entrypoint(tmp_path):
    """Cannot find the entrypoint used in dispatch."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_text(EXAMPLE_DISPATCH)
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_entrypoint_is_not_python(tmp_path):
    """The charm entrypoint has not a .py extension."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_text(
        """
        #!/bin/sh
        ./charm
    """
    )
    entrypoint = tmp_path / "charm.py"
    entrypoint.touch()
    entrypoint.chmod(0o700)
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


def test_language_entrypoint_no_exec(tmp_path):
    """The charm entrypoint is not executable."""
    dispatch = tmp_path / "dispatch"
    dispatch.write_text(EXAMPLE_DISPATCH)
    entrypoint = tmp_path / "charm.py"
    entrypoint.touch()
    result = Language().run(tmp_path)
    assert result == Language.Result.unknown


# --- tests for Framework checker


def test_framework_text_before_check():
    """The text property was accessed before running the checker."""
    with pytest.raises(RuntimeError):
        Framework().text


def test_framework_run_operator():
    """Check for Operator Framework was succesful."""
    checker = Framework()
    with patch.object(Framework, "_check_operator", lambda self, path: True):
        result = checker.run("somepath")
    assert result == Framework.Result.operator
    assert checker.text == "The charm is based on the Operator Framework."


def test_framework_run_reactive():
    """Check for Reactive Framework was succesful."""
    checker = Framework()
    with patch.object(Framework, "_check_operator", lambda self, path: False):
        with patch.object(Framework, "_check_reactive", lambda self, path: True):
            result = checker.run("somepath")
    assert result == Framework.Result.reactive
    assert checker.text == "The charm is based on the Reactive Framework."


def test_framework_run_unknown():
    """No check for any framework was succesful."""
    checker = Framework()
    with patch.object(Framework, "_check_operator", lambda self, path: False):
        with patch.object(Framework, "_check_reactive", lambda self, path: False):
            result = checker.run("somepath")
    assert result == Framework.Result.unknown
    assert checker.text == "The charm is not based on any known Framework."


@pytest.mark.parametrize(
    "import_line",
    [
        "import ops",
        "import stuff, ops, morestuff",
        "from ops import charm",
        "from ops.charm import CharmBase",
    ],
)
def test_framework_operator_used_ok(tmp_path, monkeypatch, import_line):
    """All conditions for 'framework' are in place."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text(f"{import_line}")

    # an ops directory inside venv
    opsdir = tmp_path / "venv" / "ops"
    opsdir.mkdir(parents=True)

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": entrypoint}
    )

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is True


def test_framework_operator_language_not_python(tmp_path, monkeypatch):
    """The language trait is not set to Python."""
    # an entry point that is not really python
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text("no python :)")

    # an ops directory inside venv
    opsdir = tmp_path / "venv" / "ops"
    opsdir.mkdir(parents=True)

    # the result from previously run Language
    monkeypatch.setitem(shared_state, "language", {"result": "unknown"})

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


def test_framework_operator_venv_directory_missing(tmp_path, monkeypatch):
    """The charm has not a specific 'venv' dir."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text("import ops")

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": "whatever"}
    )

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


def test_framework_operator_no_venv_ops_directory(tmp_path, monkeypatch):
    """The charm *has not* a specific 'venv/ops' dir."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text("import ops")

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": "whatever"}
    )

    # an empty venv
    venvdir = tmp_path / "venv"
    venvdir.mkdir()

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


def test_framework_operator_venv_ops_directory_is_not_a_dir(tmp_path, monkeypatch):
    """The charm has not a specific 'venv/ops' *dir*."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text("import ops")

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": "whatever"}
    )

    # an ops *file* inside venv
    opsfile = tmp_path / "venv" / "ops"
    opsfile.parent.mkdir()
    opsfile.touch()

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


def test_framework_operator_corrupted_entrypoint(tmp_path, monkeypatch):
    """Cannot parse the Python file."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text("xx --")  # not really Python

    # an ops directory inside venv
    opsdir = tmp_path / "venv" / "ops"
    opsdir.mkdir(parents=True)

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": entrypoint}
    )

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


@pytest.mark.parametrize(
    "import_line",
    [
        "import logging",
        "import whatever.ops",
        "from stuff import ops",
        "from stuff.ops import whatever",
    ],
)
def test_framework_operator_no_ops_imported(tmp_path, monkeypatch, import_line):
    """Different imports that are NOT importing the Operator Framework."""
    # an entry point that import ops
    entrypoint = tmp_path / "charm.py"
    entrypoint.write_text(f"{import_line}")

    # an ops directory inside venv
    opsdir = tmp_path / "venv" / "ops"
    opsdir.mkdir(parents=True)

    # the result from previously run Language
    monkeypatch.setitem(
        shared_state, "language", {"result": "python", "entrypoint": entrypoint}
    )

    # check
    result = Framework()._check_operator(tmp_path)
    assert result is False


@pytest.mark.parametrize(
    "import_line",
    [
        "import charms.reactive",
        "import stuff, charms.reactive, morestuff",
        "from charms.reactive import stuff",
        "from charms.reactive.stuff import Stuff",
    ],
)
@pytest.mark.parametrize(
    "metadata_result",
    [
        JujuMetadata.Result.ok,
        JujuMetadata.Result.errors,
    ],
)
def test_framework_reactive_used_ok(
    tmp_path, monkeypatch, import_line, metadata_result
):
    """The reactive framework was used.

    Parametrized args:
    - import_line: different ways to express the import
    - metadata_result: the result of JujuMetadata (which is not important as it only uses the name)
    """
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": metadata_result, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text(f"{import_line}")

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is True


def test_framework_reactive_no_metadata(tmp_path, monkeypatch):
    """No useful name from metadata."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.errors, "name": None}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("import charms.reactive")

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


def test_framework_reactive_no_entrypoint(tmp_path, monkeypatch):
    """Missing entrypoint file."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


def test_framework_reactive_unaccesible_entrypoint(tmp_path, monkeypatch):
    """Cannot read the entrypoint file."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("import charms.reactive")
    entrypoint.chmod(0o000)

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


def test_framework_reactive_corrupted_entrypoint(tmp_path, monkeypatch):
    """The entrypoint is not really a Python file."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("xx --")  # not really Python

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


def test_framework_reactive_no_wheelhouse(tmp_path, monkeypatch):
    """The wheelhouse directory does not exist."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("import charms.reactive")

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


def test_framework_reactive_no_reactive_lib(tmp_path, monkeypatch):
    """The wheelhouse directory has no reactive lib."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text("import charms.reactive")

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.noreallyreactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


@pytest.mark.parametrize(
    "import_line",
    [
        "import logging",
        "import whatever.charms.reactive",
        "import charms.whatever.reactive",
        "from stuff.charms import reactive",
        "from charms.stuff import reactive",
        "from stuff.charms.reactive import whatever",
    ],
)
def test_framework_reactive_no_reactive_imported(tmp_path, monkeypatch, import_line):
    """Different imports that are NOT importing the Reactive Framework."""
    # the result from previously run JujuMetadata
    monkeypatch.setitem(
        shared_state, "metadata", {"result": JujuMetadata.Result.ok, "name": "foobar"}
    )

    # a Python file that imports charms.reactive
    entrypoint = tmp_path / "reactive" / "foobar.py"
    entrypoint.parent.mkdir()
    entrypoint.write_text(f"{import_line}")

    # the reactive lib is used
    reactive_lib = tmp_path / "wheelhouse" / "charms.reactive-1.0.1.zip"
    reactive_lib.parent.mkdir()
    reactive_lib.touch()

    # check
    result = Framework()._check_reactive(tmp_path)
    assert result is False


# --- tests for JujuMetadata checker


def test_jujumetadata_all_ok(tmp_path):
    """All conditions ok for JujuMetadata to result ok."""
    # metdata file with proper fields
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text(
        """
        name: foobar
        summary: Small text.
        description: Lot of text.
    """
    )
    result = JujuMetadata().run(tmp_path)
    assert result == JujuMetadata.Result.ok
    assert shared_state["metadata"]["name"] == "foobar"


def test_jujumetadata_missing_file(tmp_path):
    """No metadata.yaml file at all."""
    result = JujuMetadata().run(tmp_path)
    assert result == JujuMetadata.Result.errors
    assert shared_state["metadata"]["name"] is None


def test_jujumetadata_file_corrupted(tmp_path):
    """The metadata.yaml file is not valid YAML."""
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text(" - \n-")
    result = JujuMetadata().run(tmp_path)
    assert result == JujuMetadata.Result.errors
    assert shared_state["metadata"]["name"] is None


def test_jujumetadata_missing_name(tmp_path):
    """A required "name" is missing in the metadata file."""
    # metdata file with not all fields
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text(
        """
        summary: Small text.
        description: Lot of text.
    """
    )
    result = JujuMetadata().run(tmp_path)
    assert result == JujuMetadata.Result.errors
    assert shared_state["metadata"]["name"] is None


@pytest.mark.parametrize(
    "fields",
    [
        """
    name: foobar
    summary: Small text.
    """,
        """
    name: foobar
    description: Lot of text.
    """,
    ],
)
def test_jujumetadata_missing_field(tmp_path, fields):
    """A required field is missing in the metadata file."""
    # metdata file with not all fields
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text(fields)
    result = JujuMetadata().run(tmp_path)
    assert result == JujuMetadata.Result.errors
    assert shared_state["metadata"]["name"] == "foobar"


# --- tests for analyze function


def create_fake_checker(**kwargs):
    """Create a fake Checker.

    Receive generic kwargs and process them as a dict for the defaults, as we can't declare
    the name in the function definition and then use it in the class definition.
    """
    params = dict(
        check_type="type", name="name", url="url", text="text", result="result"
    )
    params.update(kwargs)

    class FakeChecker:
        check_type = params["check_type"]
        name = params["name"]
        url = params["url"]
        text = params["text"]

        def run(self, basedir):
            return params["result"]

    return FakeChecker


def test_analyze_run_everything(config):
    """Check that analyze runs all and collect the results."""
    FakeChecker1 = create_fake_checker(
        check_type="type1", name="name1", url="url1", text="text1", result="result1"
    )
    FakeChecker2 = create_fake_checker(
        check_type="type2", name="name2", url="url2", text="text2", result="result2"
    )

    # hack the first fake checker to validate that it receives the indicated path
    def dir_validator(self, basedir):
        assert basedir == "test-buildpath"
        return "result1"

    FakeChecker1.run = dir_validator

    with patch("charmcraft.linters.CHECKERS", [FakeChecker1, FakeChecker2]):
        result = analyze(config, "test-buildpath")

    r1, r2 = result
    assert r1.check_type == "type1"
    assert r1.name == "name1"
    assert r1.url == "url1"
    assert r1.text == "text1"
    assert r1.result == "result1"
    assert r2.check_type == "type2"
    assert r2.name == "name2"
    assert r2.url == "url2"
    assert r2.text == "text2"
    assert r2.result == "result2"


def test_analyze_ignore_attribute(config):
    """Run all checkers except the ignored attribute."""
    FakeChecker1 = create_fake_checker(
        check_type=CheckType.attribute, name="name1", result="res1"
    )
    FakeChecker2 = create_fake_checker(
        check_type=CheckType.lint, name="name2", result="res2"
    )

    config.analysis.ignore.attributes.append("name1")
    with patch("charmcraft.linters.CHECKERS", [FakeChecker1, FakeChecker2]):
        result = analyze(config, "somepath")

    res1, res2 = result
    assert res1.check_type == CheckType.attribute
    assert res1.name == "name1"
    assert res1.result == IGNORED
    assert res2.check_type == CheckType.lint
    assert res2.name == "name2"
    assert res2.result == "res2"


def test_analyze_ignore_linter(config):
    """Run all checkers except the ignored linter."""
    FakeChecker1 = create_fake_checker(
        check_type=CheckType.attribute, name="name1", result="res1"
    )
    FakeChecker2 = create_fake_checker(
        check_type=CheckType.lint, name="name2", result="res2"
    )

    config.analysis.ignore.linters.append("name2")
    with patch("charmcraft.linters.CHECKERS", [FakeChecker1, FakeChecker2]):
        result = analyze(config, "somepath")

    res1, res2 = result
    assert res1.check_type == CheckType.attribute
    assert res1.name == "name1"
    assert res1.result == "res1"
    assert res2.check_type == CheckType.lint
    assert res2.name == "name2"
    assert res2.result == IGNORED


def test_analyze_crash_attribute(config):
    """The attribute checker crashes."""
    FakeChecker = create_fake_checker(check_type=CheckType.attribute, name="name")

    def raises(*a):
        raise ValueError

    FakeChecker.run = raises

    with patch("charmcraft.linters.CHECKERS", [FakeChecker]):
        result = analyze(config, "somepath")

    (res,) = result
    assert res.check_type == CheckType.attribute
    assert res.name == "name"
    assert res.result == UNKNOWN


def test_analyze_crash_lint(config):
    """The lint checker crashes."""
    FakeChecker = create_fake_checker(check_type=CheckType.lint, name="name")

    def raises(*a):
        raise ValueError

    FakeChecker.run = raises

    with patch("charmcraft.linters.CHECKERS", [FakeChecker]):
        result = analyze(config, "somepath")

    (res,) = result
    assert res.check_type == CheckType.lint
    assert res.name == "name"
    assert res.result == FATAL


# --- tests for sharing state between checkers


def test_shared_state_dependency_language_framework(config, tmp_path):
    """Verify that dependency between Language and Framework is ok in CHECKERS."""
    # simplify the list of checkers to run, but keeping the order between the two we want
    # to exercise
    test_checkers = [c for c in CHECKERS if c is Language or c is Framework]

    # create a fake complete project for the checkers to run
    dispatch = tmp_path / "dispatch"
    dispatch.write_text(EXAMPLE_DISPATCH)
    entrypoint = tmp_path / "charm.py"
    entrypoint.touch()
    entrypoint.chmod(0o700)

    with patch("charmcraft.linters.CHECKERS", test_checkers):
        result = analyze(config, tmp_path)

    r1, r2 = result
    assert r1.name == Language.name
    assert r2.name == Framework.name


def test_shared_state_dependency_jujumetadata_framework(config, tmp_path):
    """Verify that dependency between JujuMetadata and Framework is ok in CHECKERS."""
    # simplify the list of checkers to run, but keeping the order between the two we want
    # to exercise
    test_checkers = [c for c in CHECKERS if c is JujuMetadata or c is Framework]

    # create a fake metadata that even JujuMetadta ending in error, have a proper useful 'name'
    metadata_file = tmp_path / "metadata.yaml"
    metadata_file.write_text("name: testname")

    with patch("charmcraft.linters.CHECKERS", test_checkers):
        result = analyze(config, tmp_path)

    r1, r2 = result
    assert r1.name == JujuMetadata.name
    assert r2.name == Framework.name
