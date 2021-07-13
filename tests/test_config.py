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

import datetime
import logging
import os
import pathlib
from textwrap import dedent
from unittest.mock import patch

import pytest

from charmcraft import linters
from charmcraft.cmdbase import CommandError
from charmcraft.config import Base, BasesConfiguration, CharmhubConfig, Part, load
from charmcraft.utils import get_host_architecture


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
    tmp_path = create_config(
        """
        type: charm
    """
    )
    monkeypatch.chdir(tmp_path)
    fake_utcnow = datetime.datetime(1970, 1, 1, 0, 0, 2, tzinfo=datetime.timezone.utc)
    with patch("datetime.datetime") as mock:
        mock.utcnow.return_value = fake_utcnow
        config = load(None)
    assert config.type == "charm"
    assert config.project.dirpath == tmp_path
    assert config.project.config_provided
    assert config.project.started_at == fake_utcnow


def test_load_managed_mode_directory(create_config, monkeypatch, tmp_path):
    """Validate managed-mode default directory is /root/project."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHARMCRAFT_MANAGED_MODE", "1")

    # Patch out Config (and Project) to prevent directory validation checks.
    with patch("charmcraft.config.Config"):
        with patch("charmcraft.config.Project") as mock_project:
            with patch("charmcraft.config.load_yaml"):
                load(None)

    assert mock_project.call_args.kwargs["dirpath"] == pathlib.Path("/root/project")


def test_load_specific_directory_ok(create_config):
    """Init the config using charmcraft.yaml in a specific directory."""
    tmp_path = create_config(
        """
        type: charm
    """
    )
    config = load(tmp_path)
    assert config.type == "charm"
    assert config.project.dirpath == tmp_path


def test_load_optional_charmcraft_missing(tmp_path):
    """Specify a directory where the file is missing."""
    config = load(tmp_path)
    assert config.type is None
    assert config.project.dirpath == tmp_path
    assert not config.project.config_provided


def test_load_specific_directory_resolved(create_config, monkeypatch):
    """Ensure that the given directory is resolved to always show the whole path."""
    tmp_path = create_config(
        """
        type: charm
    """
    )
    # change to some dir, and reference the config dir relatively
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    config = load("../")

    assert config.type == "charm"
    assert config.project.dirpath == tmp_path


def test_load_specific_directory_expanded(create_config, monkeypatch):
    """Ensure that the given directory is user-expanded."""
    tmp_path = create_config(
        """
        type: charm
    """
    )
    # fake HOME so the '~' indication is verified to work
    monkeypatch.setitem(os.environ, "HOME", str(tmp_path))
    config = load("~")

    assert config.type == "charm"
    assert config.project.dirpath == tmp_path


# -- tests for schema restrictions


@pytest.fixture
def check_schema_error(tmp_path):
    """Helper to check the schema error."""

    def check_schema_error(expected_msg):
        """The real checker.

        Note this compares for multiple messages, as for Python 3.5 we don't have control on
        which of the verifications it will fail. After 3.5 is dropped this could be changed
        to receive only one message and compare with equality below, not inclusion.
        """
        with pytest.raises(CommandError) as cm:
            load(tmp_path)
        assert str(cm.value) == expected_msg

    return check_schema_error


def test_schema_top_level_no_extra_properties(create_config, check_schema_error):
    """Schema validation, can not add undefined properties at the top level."""
    create_config(
        """
        type: bundle
        whatever: new-stuff
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - extra field 'whatever' not permitted in top-level configuration"""
        )
    )


def test_schema_type_missing(create_config, check_schema_error):
    """Schema validation, type is mandatory."""
    create_config(
        """
        charmhub:
            api-url: https://www.canonical.com
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - must be either 'charm' or 'bundle' in field 'type'"""
        )
    )


def test_schema_type_bad_type(create_config, check_schema_error):
    """Schema validation, type is a string."""
    create_config(
        """
        type: 33
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - must be either 'charm' or 'bundle' in field 'type'"""
        )
    )


def test_schema_type_limited_values(create_config, check_schema_error):
    """Schema validation, type must be a subset of values."""
    create_config(
        """
        type: whatever
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - must be either 'charm' or 'bundle' in field 'type'"""
        )
    )


def test_schema_charmhub_api_url_bad_type(create_config, check_schema_error):
    """Schema validation, charmhub.api-url must be a string."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            api-url: 33
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.api-url'"""
        )
    )


def test_schema_charmhub_api_url_bad_format(create_config, check_schema_error):
    """Schema validation, charmhub.api-url must be a full URL."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            api-url: stuff.com
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.api-url'"""
        )
    )


def test_schema_charmhub_storage_url_bad_type(create_config, check_schema_error):
    """Schema validation, charmhub.storage-url must be a string."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            storage-url: 33
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.storage-url'"""
        )
    )


def test_schema_charmhub_storage_url_bad_format(create_config, check_schema_error):
    """Schema validation, charmhub.storage-url must be a full URL."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            storage-url: stuff.com
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.storage-url'"""
        )
    )


def test_schema_charmhub_registry_url_bad_type(create_config, check_schema_error):
    """Schema validation, charmhub.registry-url must be a string."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            registry-url: 33
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.registry-url'"""
        )
    )


def test_schema_charmhub_registry_url_bad_format(create_config, check_schema_error):
    """Schema validation, charmhub.registry-url must be a full URL."""
    create_config(
        """
        type: charm  # mandatory
        charmhub:
            registry-url: stuff.com
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - invalid or missing URL scheme in field 'charmhub.registry-url'"""
        )
    )


def test_schema_charmhub_no_extra_properties(create_config, check_schema_error):
    """Schema validation, can not add undefined properties in charmhub key."""
    create_config(
        """
        type: bundle
        charmhub:
            storage-url: https://some.server.com
            crazy: false
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - extra field 'crazy' not permitted in 'charmhub' configuration"""
        )
    )


def test_schema_basicprime_bad_init_structure(create_config, check_schema_error):
    """Schema validation, basic prime with bad parts."""
    create_config(
        """
        type: charm  # mandatory
        parts: ['foo', 'bar']
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - value is not a valid dict in field 'parts'"""
        )
    )


def test_schema_basicprime_bad_bundle_structure(create_config, check_schema_error):
    """Instantiate charmhub using a bad structure."""
    """Schema validation, basic prime with bad bundle."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            bundle: ['foo', 'bar']
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - value is not a valid dict in field 'parts.bundle'"""
        )
    )


def test_schema_basicprime_bad_prime_structure(create_config, check_schema_error):
    """Schema validation, basic prime with bad prime."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            bundle:
                prime: foo
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - value is not a valid list in field 'parts.bundle.prime'"""
        )
    )


def test_schema_basicprime_bad_prime_type_int(create_config, check_schema_error):
    """Schema validation, basic prime with a prime holding not strings."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            bundle:
                prime: [33, 'foo']
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - string type expected in field 'parts.bundle.prime[0]'"""
        )
    )


def test_schema_basicprime_bad_prime_type_empty(create_config, check_schema_error):
    """Schema validation, basic prime with a prime holding not strings."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            bundle:
                prime: ['', 'foo']
    """
    )
    check_schema_error(
        (
            "Bad charmcraft.yaml content:\n"
            "- '' must be a valid relative path (cannot be empty)"
            " in field 'parts.bundle.prime[0]'"
        )
    )


def test_schema_basicprime_bad_content_format(create_config, check_schema_error):
    """Schema validation, basic prime with a prime holding not strings."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            bundle:
                prime: ['/bar/foo', 'foo']
    """
    )
    check_schema_error(
        (
            "Bad charmcraft.yaml content:\n"
            "- '/bar/foo' must be a valid relative path (cannot start with '/')"
            " in field 'parts.bundle.prime[0]'"
            ""
        )
    )


def test_schema_unsupported_part(create_config, check_schema_error):
    """Instantiate charmhub using a bad structure."""
    """Schema validation, basic prime with bad bundle."""
    create_config(
        """
        type: charm  # mandatory
        parts:
            not-bundle: 1
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - extra field 'not-bundle' not permitted in 'parts' configuration"""
        )
    )


# -- tests for Charmhub config


def test_charmhub_frozen():
    """Cannot change values from the charmhub config."""
    config = CharmhubConfig()
    with pytest.raises(TypeError):
        config.api_url = "broken"


def test_charmhub_underscore_backwards_compatibility(create_config, tmp_path, caplog):
    """Support underscore in these attributes for a while."""
    caplog.set_level(logging.WARNING, logger="charmcraft")

    create_config(
        """
        type: charm  # mandatory
        charmhub:
            storage_url: https://server1.com
            api_url: https://server2.com
            registry_url: https://server3.com
    """
    )
    cfg = load(tmp_path)
    assert cfg.charmhub.storage_url == "https://server1.com"
    assert cfg.charmhub.api_url == "https://server2.com"
    assert cfg.charmhub.registry_url == "https://server3.com"
    deprecation_msg = "DEPRECATED: Configuration keywords are now separated using dashes."
    assert deprecation_msg in [rec.message for rec in caplog.records]


# -- tests for BasicPrime config


def test_basicprime_frozen():
    """Cannot change values from the charmhub config."""
    config = Part(prime=["foo", "bar"])
    with pytest.raises(TypeError):
        config[0] = "broken"


def test_basicprime_ok():
    """A simple building ok."""
    config = Part(prime=["foo", "bar"])
    with pytest.raises(TypeError):
        config.prime = "broken"
    assert config.prime == ["foo", "bar"]


def test_basicprime_empty():
    """Building with an empty list."""
    config = Part(prime=[])
    assert config.prime == []


# -- tests for bases


def test_no_bases_defaults_to_ubuntu_20_04_with_dn03(caplog, create_config, tmp_path):
    caplog.set_level(logging.WARNING, logger="charmcraft")
    create_config(
        """
        type: charm
    """
    )

    config = load(tmp_path)

    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [Base(name="ubuntu", channel="20.04")],
                "run-on": [Base(name="ubuntu", channel="20.04")],
            }
        )
    ]
    assert "DEPRECATED: Bases configuration is now required." in [
        rec.message for rec in caplog.records
    ]


def test_bases_minimal_long_form(create_config):
    tmp_path = create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-build-name
                channel: test-build-channel
            run-on:
              - name: test-run-name
                channel: test-run-channel
    """
    )

    config = load(tmp_path)
    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-build-name",
                        channel="test-build-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-run-name",
                        channel="test-run-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
            }
        )
    ]


def test_bases_extra_field_error(create_config, check_schema_error):
    create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-name
                channel: test-build-channel
                extra-extra: read all about it
            run-on:
              - name: test-name
                channel: test-run-channel
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - extra field 'extra-extra' not permitted in 'bases[0].build-on[0]' configuration"""
        )
    )


def test_bases_underscores_error(create_config, check_schema_error):
    create_config(
        """
        type: charm
        bases:
          - build_on:
              - name: test-name
                channel: test-build-channel
            run_on:
              - name: test-name
                channel: test-run-channel
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - field 'build-on' required in 'bases[0]' configuration
            - field 'run-on' required in 'bases[0]' configuration
            - extra field 'build_on' not permitted in 'bases[0]' configuration
            - extra field 'run_on' not permitted in 'bases[0]' configuration"""
        )
    )


def test_channel_is_yaml_number(create_config, check_schema_error):
    create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-build-name
                channel: 20.10
            run-on:
              - name: test-run-name
                channel: test-run-channel
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - string type expected in field 'bases[0].build-on[0].channel'"""
        )
    )


def test_minimal_long_form_bases(create_config):
    tmp_path = create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-build-name
                channel: test-build-channel
            run-on:
              - name: test-run-name
                channel: test-run-channel
    """
    )

    config = load(tmp_path)
    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-build-name",
                        channel="test-build-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-run-name",
                        channel="test-run-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
            }
        )
    ]


def test_complex_long_form_bases(create_config):
    tmp_path = create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-build-name-1
                channel: test-build-channel-1
              - name: test-build-name-2
                channel: test-build-channel-2
              - name: test-build-name-3
                channel: test-build-channel-3
                architectures: [riscVI]
            run-on:
              - name: test-run-name-1
                channel: test-run-channel-1
                architectures: [amd64]
              - name: test-run-name-2
                channel: test-run-channel-2
                architectures: [amd64, arm64]
              - name: test-run-name-3
                channel: test-run-channel-3
                architectures: [amd64, arm64, riscVI]
    """
    )

    config = load(tmp_path)
    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-build-name-1",
                        channel="test-build-channel-1",
                        architectures=[get_host_architecture()],
                    ),
                    Base(
                        name="test-build-name-2",
                        channel="test-build-channel-2",
                        architectures=[get_host_architecture()],
                    ),
                    Base(
                        name="test-build-name-3",
                        channel="test-build-channel-3",
                        architectures=["riscVI"],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-run-name-1",
                        channel="test-run-channel-1",
                        architectures=["amd64"],
                    ),
                    Base(
                        name="test-run-name-2",
                        channel="test-run-channel-2",
                        architectures=["amd64", "arm64"],
                    ),
                    Base(
                        name="test-run-name-3",
                        channel="test-run-channel-3",
                        architectures=["amd64", "arm64", "riscVI"],
                    ),
                ],
            }
        )
    ]


def test_multiple_long_form_bases(create_config):
    tmp_path = create_config(
        """
        type: charm
        bases:
          - build-on:
              - name: test-build-name-1
                channel: test-build-channel-1
            run-on:
              - name: test-run-name-1
                channel: test-run-channel-1
                architectures: [amd64, arm64]
          - build-on:
              - name: test-build-name-2
                channel: test-build-channel-2
            run-on:
              - name: test-run-name-2
                channel: test-run-channel-2
                architectures: [amd64, arm64]
    """
    )

    config = load(tmp_path)
    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-build-name-1",
                        channel="test-build-channel-1",
                        architectures=[get_host_architecture()],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-run-name-1",
                        channel="test-run-channel-1",
                        architectures=["amd64", "arm64"],
                    ),
                ],
            }
        ),
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-build-name-2",
                        channel="test-build-channel-2",
                        architectures=[get_host_architecture()],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-run-name-2",
                        channel="test-run-channel-2",
                        architectures=["amd64", "arm64"],
                    ),
                ],
            }
        ),
    ]


def test_bases_minimal_short_form(create_config):
    tmp_path = create_config(
        """
        type: charm
        bases:
          - name: test-name
            channel: test-channel
    """
    )

    config = load(tmp_path)
    assert config.bases == [
        BasesConfiguration(
            **{
                "build-on": [
                    Base(
                        name="test-name",
                        channel="test-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
                "run-on": [
                    Base(
                        name="test-name",
                        channel="test-channel",
                        architectures=[get_host_architecture()],
                    ),
                ],
            }
        )
    ]


def test_bases_short_form_extra_field_error(create_config, check_schema_error):
    create_config(
        """
        type: charm
        bases:
          - name: test-name
            channel: test-channel
            extra-extra: read all about it
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - extra field 'extra-extra' not permitted in 'bases[0]' configuration"""
        )
    )


def test_bases_short_form_missing_field_error(create_config, check_schema_error):
    create_config(
        """
        type: charm
        bases:
          - name: test-name
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - field 'channel' required in 'bases[0]' configuration"""
        )
    )


def test_bases_mixed_form_errors(create_config, check_schema_error):
    """Only the short-form errors are exposed as its the first validation pass."""
    create_config(
        """
        type: charm
        bases:
          - name: test-name
          - build-on:
              - name: test-build-name
            run-on:
              - name: test-run-name
    """
    )

    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - field 'channel' required in 'bases[0]' configuration"""
        )
    )


# -- tests for analysis


@pytest.fixture
def create_checker(monkeypatch):
    """Helper to patch and add checkers to the real structure."""
    test_checkers = []
    monkeypatch.setattr(linters, "CHECKERS", test_checkers)

    def add_checker(c_name, c_type):
        class FakeChecker:
            name = c_name
            check_type = c_type

        test_checkers.append(FakeChecker)

    return add_checker


def test_schema_analysis_missing(create_config, tmp_path):
    """No analysis configuration leads to some defaults in place."""
    create_config(
        """
        type: charm  # mandatory
    """
    )
    config = load(tmp_path)
    assert config.analysis.ignore.attributes == []
    assert config.analysis.ignore.linters == []


def test_schema_analysis_full_struct_just_empty(create_config, tmp_path):
    """Complete analysis structure, empty."""
    create_config(
        """
        type: charm  # mandatory
        analysis:
            ignore:
                attributes: []
                linters: []
    """
    )
    config = load(tmp_path)
    assert config.analysis.ignore.attributes == []
    assert config.analysis.ignore.linters == []


def test_schema_analysis_ignore_attributes(
    create_config, check_schema_error, tmp_path, create_checker
):
    """Some attributes are correctly ignored."""
    create_checker("check_ok_1", linters.CheckType.attribute)
    create_checker("check_ok_2", linters.CheckType.attribute)
    create_config(
        """
        type: charm  # mandatory
        analysis:
            ignore:
                attributes: [check_ok_1, check_ok_2]
    """
    )
    config = load(tmp_path)
    assert config.analysis.ignore.attributes == ["check_ok_1", "check_ok_2"]
    assert config.analysis.ignore.linters == []


def test_schema_analysis_ignore_linters(
    create_config, check_schema_error, tmp_path, create_checker
):
    """Some linters are correctly ignored."""
    create_checker("check_ok_1", linters.CheckType.warning)
    create_checker("check_ok_2", linters.CheckType.error)
    create_config(
        """
        type: charm  # mandatory
        analysis:
            ignore:
                linters: [check_ok_1, check_ok_2]
    """
    )
    config = load(tmp_path)
    assert config.analysis.ignore.attributes == []
    assert config.analysis.ignore.linters == ["check_ok_1", "check_ok_2"]


def test_schema_analysis_ignore_attribute_missing(
    create_config, check_schema_error, tmp_path, create_checker
):
    """An attribute specified to ignore is missing in the system."""
    create_checker("check_ok_1", linters.CheckType.attribute)
    create_checker("check_ok_2", linters.CheckType.warning)
    create_config(
        """
        type: charm  # mandatory
        analysis:
            ignore:
                attributes: [check_ok_1, check_missing]
                linters: [check_ok_2]
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - Bad attribute name 'check_missing' in field 'analysis.ignore.attributes[1]'"""
        )
    )


def test_schema_analysis_ignore_linter_missing(
    create_config, check_schema_error, tmp_path, create_checker
):
    """A linter specified to ignore is missing in the system."""
    create_checker("check_ok_1", linters.CheckType.attribute)
    create_checker("check_ok_2", linters.CheckType.warning)
    create_config(
        """
        type: charm  # mandatory
        analysis:
            ignore:
                attributes: [check_ok_1]
                linters: [check_ok_2, check_missing]
    """
    )
    check_schema_error(
        dedent(
            """\
            Bad charmcraft.yaml content:
            - Bad linter name 'check_missing' in field 'analysis.ignore.linters[1]'"""
        )
    )
