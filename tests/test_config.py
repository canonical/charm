# Copyright 2020 Canonical Ltd.
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

import attr
import pytest

from charmcraft.cmdbase import CommandError
from charmcraft.config import (
    _BasicPrime,
    _CharmhubConfig,
    _check_url,
    load,
)


@pytest.fixture
def create_config(tmp_path):
    """Helper to create the config."""
    def create_config(text):
        test_file = tmp_path / "charmcraft.yaml"
        test_file.write_text(text)
        return tmp_path
    return create_config


# -- tests for the config loading

def test_load_current_directory(create_config, monkeypatch):
    """Init the config using charmcraft.yaml in current directory."""
    tmp_path = create_config("""
        type: charm
    """)
    monkeypatch.chdir(tmp_path)
    config = load(None)
    assert config.type == 'charm'
    assert config.project.dirpath == tmp_path


def test_load_specific_directory_ok(create_config):
    """Init the config using charmcraft.yaml in a specific directory."""
    tmp_path = create_config("""
        type: charm
    """)
    config = load(tmp_path)
    assert config.type == 'charm'
    assert config.project.dirpath == tmp_path


def test_load_optional_charmcraft_missing(tmp_path):
    """Specify a directory where the file is missing."""
    config = load(tmp_path)
    assert config is None


# -- tests for schema restrictions

@pytest.fixture
def check_schema_error(tmp_path):
    """Helper to check the schema error."""
    def check_schema_error(expected_msg):
        with pytest.raises(CommandError) as cm:
            load(tmp_path)
        assert str(cm.value) == expected_msg
    return check_schema_error


def test_schema_type_mandatory(create_config, check_schema_error):
    """Schema validation, type is mandatory."""
    create_config("""
        someconfig: None
    """)
    check_schema_error("Bad charmcraft.yaml content; missing fields: type.")


def test_schema_type_bad_type(create_config, check_schema_error):
    """Schema validation, type is a string."""
    create_config("""
        type: 33
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'type' field must be a string: got 'int'.")


def test_schema_type_limited_values(create_config, check_schema_error):
    """Schema validation, type must be a subset of values."""
    create_config("""
        type: whatever
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'type' field must be one of: 'charm', 'bundle'.")


def test_schema_charmhub_api_url_bad_type(create_config, check_schema_error):
    """Schema validation, charmhub.api_url must be a string."""
    create_config("""
        type: charm  # mandatory
        charmhub:
            api_url: 33
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'charmhub.api_url' field must be a string: got 'int'.")


def test_schema_charmhub_api_url_bad_format(create_config, check_schema_error):
    """Schema validation, charmhub.api_url must be a full URL."""
    create_config("""
        type: charm  # mandatory
        charmhub:
            api_url: stuff.com
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'charmhub.api_url' field must be a full URL (e.g. "
        "'https://some.server.com'): got 'stuff.com'.")


def test_schema_charmhub_storage_url_bad_type(create_config, check_schema_error):
    """Schema validation, charmhub.storage_url must be a string."""
    create_config("""
        type: charm  # mandatory
        charmhub:
            storage_url: 33
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'charmhub.storage_url' field must be a string: "
        "got 'int'.")


def test_schema_charmhub_storage_url_bad_format(create_config, check_schema_error):
    """Schema validation, charmhub.storage_url must be a full URL."""
    create_config("""
        type: charm  # mandatory
        charmhub:
            storage_url: stuff.com
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'charmhub.storage_url' field must be a full URL (e.g. "
        "'https://some.server.com'): got 'stuff.com'.")


def test_schema_basicprime_bad_init_structure(create_config, check_schema_error):
    """Schema validation, basic prime with bad parts."""
    create_config("""
        type: charm  # mandatory
        parts: ['foo', 'bar']
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'parts' field must be a dict: got 'list'.")


def test_schema_basicprime_bad_bundle_structure(create_config, check_schema_error):
    """Instantiate charmhub using a bad structure."""
    """Schema validation, basic prime with bad bundle."""
    create_config("""
        type: charm  # mandatory
        parts:
            bundle: ['foo', 'bar']
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'parts.bundle' field must be a dict: got 'list'.")


def test_schema_basicprime_bad_prime_structure(create_config, check_schema_error):
    """Schema validation, basic prime with bad prime."""
    create_config("""
        type: charm  # mandatory
        parts:
            bundle:
                prime: foo
    """)
    check_schema_error(
        "Bad charmcraft.yaml content; the 'parts.bundle.prime' field must be a list: got 'str'.")


# -- tests for different validators

def test_url_ok():
    """URL format is ok."""
    assert _check_url('https://some.server.com')


def test_url_no_scheme():
    """URL format is wrong, missing scheme."""
    with pytest.raises(ValueError) as cm:
        _check_url('some.server.com')
    assert str(cm.value) == "must be a full URL (e.g. 'https://some.server.com')"


def test_url_no_netloc():
    """URL format is wrong, missing network location."""
    with pytest.raises(ValueError) as cm:
        _check_url('https://')
    assert str(cm.value) == "must be a full URL (e.g. 'https://some.server.com')"


# -- tests for Charmhub config

def test_charmhub_frozen():
    """Cannot change values from the charmhub config."""
    config = _CharmhubConfig()
    with pytest.raises(attr.exceptions.FrozenInstanceError):
        config.api_url = 'broken'


# -- tests for BasicPrime config

def test_basicprime_frozen():
    """Cannot change values from the charmhub config."""
    config = _BasicPrime.from_dict({
        'bundle': {
            'prime': ['foo', 'bar'],
        }
    })
    with pytest.raises(TypeError):
        config[0] = 'broken'


def test_basicprime_ok():
    """A simple building ok."""
    config = _BasicPrime.from_dict({
        'bundle': {
            'prime': ['foo', 'bar'],
        }
    })
    assert config == ('foo', 'bar')


def test_basicprime_bad_paths():
    """Indicated paths must be relative."""
    with pytest.raises(CommandError) as cm:
        _BasicPrime.from_dict({
            'bundle': {
                'prime': ['foo', '/tmp/bar'],
            }
        })
    assert str(cm.value) == (
        "Bad charmcraft.yaml content; the paths specifications in 'parts.bundle.prime' "
        "must be relative: found '/tmp/bar'.")
