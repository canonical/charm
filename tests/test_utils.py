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

import logging
import os
import pathlib

import pytest

from charmcraft.cmdbase import CommandError
from charmcraft.utils import (
    ResourceOption,
    SingleOptionEnsurer,
    load_yaml,
    make_executable,
    useful_filepath,
)


def test_make_executable_read_bits(tmp_path):
    pth = tmp_path / "test"
    pth.touch(mode=0o640)
    # sanity check
    assert pth.stat().st_mode & 0o777 == 0o640
    with pth.open() as fd:
        make_executable(fd)
        # only read bits got made executable
        assert pth.stat().st_mode & 0o777 == 0o750


def test_load_yaml_success(tmp_path):
    test_file = tmp_path / "testfile.yaml"
    test_file.write_text("""
        foo: 33
    """)
    content = load_yaml(test_file)
    assert content == {'foo': 33}


def test_load_yaml_no_file(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    test_file = tmp_path / "testfile.yaml"
    content = load_yaml(test_file)
    assert content is None

    expected = "Couldn't find config file {}".format(test_file)
    assert [expected] == [rec.message for rec in caplog.records]


def test_load_yaml_directory(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    test_file = tmp_path / "testfile.yaml"
    test_file.mkdir()
    content = load_yaml(test_file)
    assert content is None

    expected = "Couldn't find config file {}".format(test_file)
    assert [expected] == [rec.message for rec in caplog.records]


def test_load_yaml_corrupted_format(tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="charmcraft.commands")

    test_file = tmp_path / "testfile.yaml"
    test_file.write_text("""
        foo: [1, 2
    """)
    content = load_yaml(test_file)
    assert content is None

    (logged,) = [rec.message for rec in caplog.records]
    assert "Failed to read/parse config file {}".format(test_file) in logged
    assert "ParserError" in logged


def test_load_yaml_file_problem(tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="charmcraft.commands")

    test_file = tmp_path / "testfile.yaml"
    test_file.write_text("""
        foo: bar
    """)
    test_file.chmod(0o000)
    content = load_yaml(test_file)
    assert content is None

    (logged,) = [rec.message for rec in caplog.records]
    assert "Failed to read/parse config file {}".format(test_file) in logged
    assert "PermissionError" in logged


# -- tests for the SingleOptionEnsurer helper class

def test_singleoptionensurer_convert_ok():
    """Work fine with one call, convert as expected."""
    soe = SingleOptionEnsurer(int)
    assert soe('33') == 33


def test_singleoptionensurer_too_many():
    """Raise an error after one ok call."""
    soe = SingleOptionEnsurer(int)
    assert soe('33') == 33
    with pytest.raises(ValueError) as cm:
        soe('33')
    assert str(cm.value) == "the option can be specified only once"


# -- tests for the ResourceOption helper class

def test_resourceoption_convert_ok():
    """Convert as expected."""
    r = ResourceOption()("foo:13")
    assert r.name == 'foo'
    assert r.revision == 13


@pytest.mark.parametrize('value', [
    'foo15',  # no separation
    'foo:',  # no revision
    'foo:x3',  # no int
    'foo:0',  # revision 0 is not allowed
    'foo:-1',  # negative revisions are not allowed
    ':15',  # no name
    '  :15',  # no name, really!
    'foo:bar:15',  # invalid name, anyway
])
def test_resourceoption_convert_error(value):
    """Error while converting."""
    with pytest.raises(ValueError) as cm:
        ResourceOption()(value)
    assert str(cm.value) == (
        "the resource format must be <name>:<revision> (revision being a positive integer)")


# -- tests for the useful_filepath helper

def test_usefulfilepath_pathlib(tmp_path):
    """Convert the string to Path."""
    test_file = tmp_path / 'testfile.bin'
    test_file.touch()
    path = useful_filepath(str(test_file))
    assert path == test_file
    assert isinstance(path, pathlib.Path)


def test_usefulfilepath_home_expanded(tmp_path, monkeypatch):
    """Home-expand the indicated path."""
    fake_home = tmp_path / 'homedir'
    fake_home.mkdir()
    test_file = fake_home / 'testfile.bin'
    test_file.touch()

    monkeypatch.setitem(os.environ, 'HOME', str(fake_home))
    path = useful_filepath('~/testfile.bin')
    assert path == test_file


def test_usefulfilepath_missing():
    """The indicated path is not there."""
    with pytest.raises(CommandError) as cm:
        useful_filepath('not_really_there.txt')
    assert str(cm.value) == "Cannot access 'not_really_there.txt'."


def test_usefulfilepath_inaccessible(tmp_path):
    """The indicated path is not readable."""
    test_file = tmp_path / 'testfile.bin'
    test_file.touch(mode=0o000)
    with pytest.raises(CommandError) as cm:
        useful_filepath(str(test_file))
    assert str(cm.value) == "Cannot access {!r}.".format(str(test_file))


def test_usefulfilepath_not_a_file(tmp_path):
    """The indicated path is not a file."""
    with pytest.raises(CommandError) as cm:
        useful_filepath(str(tmp_path))
    assert str(cm.value) == "{!r} is not a file.".format(str(tmp_path))
