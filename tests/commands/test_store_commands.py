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

"""Tests for the Store commands (code in store/__init__.py)."""

import datetime
import hashlib
import logging
import pathlib
import zipfile
from argparse import Namespace, ArgumentParser
from unittest.mock import patch, call, MagicMock, ANY

import dateutil.parser
import pytest
import yaml

from charmcraft.config import CharmhubConfig
from charmcraft.cmdbase import CommandError
from charmcraft.commands.store import (
    CreateLibCommand,
    EntityType,
    FetchLibCommand,
    ListLibCommand,
    ListNamesCommand,
    ListResourceRevisionsCommand,
    ListResourcesCommand,
    ListRevisionsCommand,
    LoginCommand,
    LogoutCommand,
    PublishLibCommand,
    RegisterBundleNameCommand,
    RegisterCharmNameCommand,
    ReleaseCommand,
    StatusCommand,
    UploadCommand,
    UploadResourceCommand,
    WhoamiCommand,
    _get_lib_info,
    get_name_from_metadata,
    get_name_from_zip,
)
from charmcraft.commands.store.store import (
    Base,
    Channel,
    Entity,
    Error,
    Library,
    RegistryCredentials,
    Release,
    Resource,
    ResourceRevision,
    Revision,
    Uploaded,
    User,
)
from charmcraft.utils import (
    ResourceOption,
    SingleOptionEnsurer,
    get_templates_environment,
    useful_filepath,
)
from tests import factory

# used a lot!
noargs = Namespace()


@pytest.fixture
def store_mock():
    """The fixture to fake the store layer in all the tests."""
    store_mock = MagicMock()

    def validate_config(config):
        """Check that the store received the Charmhub configuration."""
        assert config == CharmhubConfig()
        return store_mock

    with patch("charmcraft.commands.store.Store", validate_config):
        yield store_mock


@pytest.fixture
def add_cleanup():
    """Generic cleaning helper."""
    to_cleanup = []

    def f(func, *args, **kwargs):
        """Store the cleaning actions for later."""
        to_cleanup.append((func, args, kwargs))

    yield f

    for func, args, kwargs in to_cleanup:
        func(*args, **kwargs)


# -- tests for helpers


def test_get_name_from_metadata_ok(tmp_path, monkeypatch):
    """The metadata file is valid yaml, but there is no name."""
    monkeypatch.chdir(tmp_path)

    # put a valid metadata
    metadata_file = tmp_path / "metadata.yaml"
    with metadata_file.open("wb") as fh:
        fh.write(b"name: test-name")

    result = get_name_from_metadata()
    assert result == "test-name"


def test_get_name_from_metadata_no_file(tmp_path, monkeypatch):
    """No metadata file to get info."""
    monkeypatch.chdir(tmp_path)
    result = get_name_from_metadata()
    assert result is None


def test_get_name_from_metadata_bad_content_garbage(tmp_path, monkeypatch):
    """The metadata file is broken."""
    monkeypatch.chdir(tmp_path)

    # put a broken metadata
    metadata_file = tmp_path / "metadata.yaml"
    with metadata_file.open("wb") as fh:
        fh.write(b"\b00\bff -- not a realy yaml stuff")

    result = get_name_from_metadata()
    assert result is None


def test_get_name_from_metadata_bad_content_no_name(tmp_path, monkeypatch):
    """The metadata file is valid yaml, but there is no name."""
    monkeypatch.chdir(tmp_path)

    # put a broken metadata
    metadata_file = tmp_path / "metadata.yaml"
    with metadata_file.open("wb") as fh:
        fh.write(b"{}")

    result = get_name_from_metadata()
    assert result is None


# -- tests for auth commands


def test_login(caplog, store_mock, config):
    """Simple login case."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    store_mock.whoami.return_value = User(name="John Doe", username="jdoe", userid="-1")

    LoginCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.login(),
        call.whoami(),
    ]
    assert ["Logged in as 'jdoe'."] == [rec.message for rec in caplog.records]


def test_logout(caplog, store_mock, config):
    """Simple logout case."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    LogoutCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.logout(),
    ]
    assert ["Charmhub token cleared."] == [rec.message for rec in caplog.records]


def test_whoami(caplog, store_mock, config):
    """Simple whoami case."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = User(name="John Doe", username="jdoe", userid="-1")
    store_mock.whoami.return_value = store_response

    WhoamiCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.whoami(),
    ]
    expected = [
        "name:      John Doe",
        "username:  jdoe",
        "id:        -1",
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for name-related commands


def test_register_charm_name(caplog, store_mock, config):
    """Simple register_name case for a charm."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    args = Namespace(name="testname")
    RegisterCharmNameCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.register_name("testname", EntityType.charm),
    ]
    expected = "You are now the publisher of charm 'testname' in Charmhub."
    assert [expected] == [rec.message for rec in caplog.records]


def test_register_bundle_name(caplog, store_mock, config):
    """Simple register_name case for a bundl."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    args = Namespace(name="testname")
    RegisterBundleNameCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.register_name("testname", EntityType.bundle),
    ]
    expected = "You are now the publisher of bundle 'testname' in Charmhub."
    assert [expected] == [rec.message for rec in caplog.records]


def test_list_registered_empty(caplog, store_mock, config):
    """List registered with empty response."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = []
    store_mock.list_registered_names.return_value = store_response

    ListNamesCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.list_registered_names(),
    ]
    expected = "No charms or bundles registered."
    assert [expected] == [rec.message for rec in caplog.records]


def test_list_registered_one_private(caplog, store_mock, config):
    """List registered with one private item in the response."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        Entity(entity_type="charm", name="charm", private=True, status="status"),
    ]
    store_mock.list_registered_names.return_value = store_response

    ListNamesCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.list_registered_names(),
    ]
    expected = [
        "Name    Type    Visibility    Status",
        "charm   charm   private       status",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_list_registered_one_public(caplog, store_mock, config):
    """List registered with one public item in the response."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        Entity(entity_type="charm", name="charm", private=False, status="status"),
    ]
    store_mock.list_registered_names.return_value = store_response

    ListNamesCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.list_registered_names(),
    ]
    expected = [
        "Name    Type    Visibility    Status",
        "charm   charm   public        status",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_list_registered_several(caplog, store_mock, config):
    """List registered with several itemsssssssss in the response."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        Entity(entity_type="charm", name="charm1", private=True, status="simple status"),
        Entity(entity_type="charm", name="charm2-long-name", private=False, status="other"),
        Entity(entity_type="charm", name="charm3", private=True, status="super long status"),
        Entity(
            entity_type="bundle",
            name="somebundle",
            private=False,
            status="bundle status",
        ),
    ]
    store_mock.list_registered_names.return_value = store_response

    ListNamesCommand("group", config).run(noargs)

    assert store_mock.mock_calls == [
        call.list_registered_names(),
    ]
    expected = [
        "Name              Type    Visibility    Status",
        "charm1            charm   private       simple status",
        "charm2-long-name  charm   public        other",
        "charm3            charm   private       super long status",
        "somebundle        bundle  public        bundle status",
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for upload command


def _build_zip_with_yaml(zippath, filename, *, content=None, raw_yaml=None):
    """Create a yaml named 'filename' with given content, inside a zip file in 'zippath'."""
    if raw_yaml is None:
        raw_yaml = yaml.dump(content).encode("ascii")
    with zipfile.ZipFile(str(zippath), "w") as zf:
        zf.writestr(filename, raw_yaml)


def test_get_name_bad_zip(tmp_path):
    """Get the name from a bad zip file."""
    bad_zip = tmp_path / "badstuff.zip"
    bad_zip.write_text("I'm not really a zip file")

    with pytest.raises(CommandError) as cm:
        get_name_from_zip(bad_zip)
    assert str(cm.value) == "Cannot open '{}' (bad zip file).".format(bad_zip)


def test_get_name_charm_ok(tmp_path):
    """Get the name from a charm file, all ok."""
    test_zip = tmp_path / "some.zip"
    test_name = "whatever"
    _build_zip_with_yaml(test_zip, "metadata.yaml", content={"name": test_name})

    name = get_name_from_zip(test_zip)
    assert name == test_name


@pytest.mark.parametrize(
    "yaml_content",
    [
        b"=",  # invalid yaml
        b"foo: bar",  # missing 'name'
    ],
)
def test_get_name_charm_bad_metadata(tmp_path, yaml_content):
    """Get the name from a charm file, but with a wrong metadata.yaml."""
    bad_zip = tmp_path / "badstuff.zip"
    _build_zip_with_yaml(bad_zip, "metadata.yaml", raw_yaml=yaml_content)

    with pytest.raises(CommandError) as cm:
        get_name_from_zip(bad_zip)
    assert str(cm.value) == (
        "Bad 'metadata.yaml' file inside charm zip "
        "'{}': must be a valid YAML with a 'name' key.".format(bad_zip)
    )


def test_get_name_bundle_ok(tmp_path):
    """Get the name from a bundle file, all ok."""
    test_zip = tmp_path / "some.zip"
    test_name = "whatever"
    _build_zip_with_yaml(test_zip, "bundle.yaml", content={"name": test_name})

    name = get_name_from_zip(test_zip)
    assert name == test_name


@pytest.mark.parametrize(
    "yaml_content",
    [
        b"=",  # invalid yaml
        b"foo: bar",  # missing 'name'
    ],
)
def test_get_name_bundle_bad_data(tmp_path, yaml_content):
    """Get the name from a bundle file, but with a bad bundle.yaml."""
    bad_zip = tmp_path / "badstuff.zip"
    _build_zip_with_yaml(bad_zip, "bundle.yaml", raw_yaml=yaml_content)

    with pytest.raises(CommandError) as cm:
        get_name_from_zip(bad_zip)
    assert str(cm.value) == (
        "Bad 'bundle.yaml' file inside bundle zip '{}': "
        "must be a valid YAML with a 'name' key.".format(bad_zip)
    )


def test_get_name_nor_charm_nor_bundle(tmp_path):
    """Get the name from a zip that has no metadata.yaml nor bundle.yaml."""
    bad_zip = tmp_path / "badstuff.zip"
    _build_zip_with_yaml(bad_zip, "whatever.yaml", content={})

    with pytest.raises(CommandError) as cm:
        get_name_from_zip(bad_zip)
    assert str(cm.value) == (
        "The indicated zip file '{}' is not a charm ('metadata.yaml' not found) nor a bundle "
        "('bundle.yaml' not found).".format(bad_zip)
    )


def test_upload_parameters_filepath_type(config):
    """The filepath parameter implies a set of validations."""
    cmd = UploadCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "filepath"]
    assert action.type is useful_filepath


def test_upload_call_ok(caplog, store_mock, config, tmp_path):
    """Simple upload, success result."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = Uploaded(ok=True, status=200, revision=7, errors=[])
    store_mock.upload.return_value = store_response

    test_charm = tmp_path / "mystuff.charm"
    _build_zip_with_yaml(test_charm, "metadata.yaml", content={"name": "mycharm"})
    args = Namespace(filepath=test_charm, release=[])
    UploadCommand("group", config).run(args)

    assert store_mock.mock_calls == [call.upload("mycharm", test_charm)]
    expected = "Revision 7 of 'mycharm' created"
    assert [expected] == [rec.message for rec in caplog.records]


def test_upload_call_error(caplog, store_mock, config, tmp_path):
    """Simple upload but with a response indicating an error."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    errors = [
        Error(message="text 1", code="missing-stuff"),
        Error(message="other long error text", code="broken"),
    ]
    store_response = Uploaded(ok=False, status=400, revision=None, errors=errors)
    store_mock.upload.return_value = store_response

    test_charm = tmp_path / "mystuff.charm"
    _build_zip_with_yaml(test_charm, "metadata.yaml", content={"name": "mycharm"})
    args = Namespace(filepath=test_charm, release=[])
    UploadCommand("group", config).run(args)

    assert store_mock.mock_calls == [call.upload("mycharm", test_charm)]
    expected = [
        "Upload failed with status 400:",
        "- missing-stuff: text 1",
        "- broken: other long error text",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_call_ok_including_release(caplog, store_mock, config, tmp_path):
    """Upload with a release included, success result."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = Uploaded(ok=True, status=200, revision=7, errors=[])
    store_mock.upload.return_value = store_response

    test_charm = tmp_path / "mystuff.charm"
    _build_zip_with_yaml(test_charm, "metadata.yaml", content={"name": "mycharm"})
    args = Namespace(filepath=test_charm, release=["edge"])
    UploadCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.upload("mycharm", test_charm),
        call.release("mycharm", 7, ["edge"]),
    ]
    expected = [
        "Revision 7 of 'mycharm' created",
        "Revision released to edge",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_call_ok_including_release_multiple(caplog, store_mock, config, tmp_path):
    """Upload with release to two channels included, success result."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = Uploaded(ok=True, status=200, revision=7, errors=[])
    store_mock.upload.return_value = store_response

    test_charm = tmp_path / "mystuff.charm"
    _build_zip_with_yaml(test_charm, "metadata.yaml", content={"name": "mycharm"})
    args = Namespace(filepath=test_charm, release=["edge", "stable"])
    UploadCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.upload("mycharm", test_charm),
        call.release("mycharm", 7, ["edge", "stable"]),
    ]
    expected = [
        "Revision 7 of 'mycharm' created",
        "Revision released to edge, stable",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_call_error_including_release(caplog, store_mock, config, tmp_path):
    """Upload with a realsea but the upload went wrong, so no release."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    errors = [Error(message="text", code="problem")]
    store_response = Uploaded(ok=False, status=400, revision=None, errors=errors)
    store_mock.upload.return_value = store_response

    test_charm = tmp_path / "mystuff.charm"
    _build_zip_with_yaml(test_charm, "metadata.yaml", content={"name": "mycharm"})
    args = Namespace(filepath=test_charm, release=["edge"])
    UploadCommand("group", config).run(args)

    # check the upload was attempted, but not the release!
    assert store_mock.mock_calls == [call.upload("mycharm", test_charm)]


def test_upload_charm_with_init_template_todo_token(tmp_path, config):
    """Avoid uploading a charm that is not really ready to be shown to the world."""
    # create a charm zip file all valid but with files having the token from
    # the templates used by 'init' command
    test_charm = tmp_path / "mystuff.charm"
    with zipfile.ZipFile(str(test_charm), "w") as zf:
        zf.writestr("metadata.yaml", yaml.dump({"name": "mycharm"}).encode("ascii"))
        zf.writestr("somefile.cfg", b"# TEMPLATE-TODO: please take a look to this.")
        zf.writestr("file_ok.cfg", b"This is fine :).")
        zf.writestr("othertainted.txt", b"# TEMPLATE-TODO: need to fix.")

    args = Namespace(filepath=test_charm, release=[])
    expected_msg = (
        "Cannot upload the charm as it include the following files with a leftover "
        "TEMPLATE-TODO token from when the project was created using the 'init' "
        "command: somefile.cfg, othertainted.txt"
    )
    with pytest.raises(CommandError, match=expected_msg):
        UploadCommand("group", config).run(args)


# -- tests for list revisions command


def test_revisions_simple(caplog, store_mock, config):
    """Happy path of one result from the Store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    bases = [Base(architecture="amd64", channel="20.04", name="ubuntu")]
    store_response = [
        Revision(
            revision=1,
            version="v1",
            created_at=datetime.datetime(2020, 7, 3, 20, 30, 40),
            status="accepted",
            errors=[],
            bases=bases,
        ),
    ]
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_revisions("testcharm"),
    ]
    expected = [
        "Revision    Version    Created at    Status",
        "1           v1         2020-07-03    accepted",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_revisions_empty(caplog, store_mock, config):
    """No results from the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = []
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    expected = [
        "No revisions found.",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_revisions_ordered_by_revision(caplog, store_mock, config):
    """Results are presented ordered by revision in the table."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    # three Revisions with all values weirdly similar, the only difference is revision, so
    # we really assert later that it was used for ordering
    tstamp = datetime.datetime(2020, 7, 3, 20, 30, 40)
    bases = [Base(architecture="amd64", channel="20.04", name="ubuntu")]
    store_response = [
        Revision(
            revision=1,
            version="v1",
            created_at=tstamp,
            status="accepted",
            errors=[],
            bases=bases,
        ),
        Revision(
            revision=3,
            version="v1",
            created_at=tstamp,
            status="accepted",
            errors=[],
            bases=bases,
        ),
        Revision(
            revision=2,
            version="v1",
            created_at=tstamp,
            status="accepted",
            errors=[],
            bases=bases,
        ),
    ]
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    expected = [
        "Revision    Version    Created at    Status",
        "3           v1         2020-07-03    accepted",
        "2           v1         2020-07-03    accepted",
        "1           v1         2020-07-03    accepted",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_revisions_version_null(caplog, store_mock, config):
    """Support the case of version being None."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    bases = [Base(architecture="amd64", channel="20.04", name="ubuntu")]
    store_response = [
        Revision(
            revision=1,
            version=None,
            created_at=datetime.datetime(2020, 7, 3, 20, 30, 40),
            status="accepted",
            errors=[],
            bases=bases,
        ),
    ]
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    expected = [
        "Revision    Version    Created at    Status",
        "1                      2020-07-03    accepted",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_revisions_errors_simple(caplog, store_mock, config):
    """Support having one case with a simple error."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    bases = [Base(architecture="amd64", channel="20.04", name="ubuntu")]
    store_response = [
        Revision(
            revision=1,
            version=None,
            created_at=datetime.datetime(2020, 7, 3, 20, 30, 40),
            status="rejected",
            errors=[Error(message="error text", code="broken")],
            bases=bases,
        ),
    ]
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    expected = [
        "Revision    Version    Created at    Status",
        "1                      2020-07-03    rejected: error text [broken]",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_revisions_errors_multiple(caplog, store_mock, config):
    """Support having one case with multiple errors."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    bases = [Base(architecture="amd64", channel="20.04", name="ubuntu")]
    store_response = [
        Revision(
            revision=1,
            version=None,
            created_at=datetime.datetime(2020, 7, 3, 20, 30, 40),
            status="rejected",
            errors=[
                Error(message="text 1", code="missing-stuff"),
                Error(message="other long error text", code="broken"),
            ],
            bases=bases,
        ),
    ]
    store_mock.list_revisions.return_value = store_response

    args = Namespace(name="testcharm")
    ListRevisionsCommand("group", config).run(args)

    expected = [
        "Revision    Version    Created at    Status",
        "1                      2020-07-03    rejected: text 1 [missing-stuff]; other long error text [broken]",  # NOQA
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for the release command


def test_release_simple_ok(caplog, store_mock, config):
    """Simple case of releasing a revision ok."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channels = ["somechannel"]
    args = Namespace(name="testcharm", revision=7, channel=channels, resource=[])
    ReleaseCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.release("testcharm", 7, channels, []),
    ]

    expected = "Revision 7 of charm 'testcharm' released to somechannel"
    assert [expected] == [rec.message for rec in caplog.records]


def test_release_simple_multiple_channels(caplog, store_mock, config):
    """Releasing to multiple channels."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    args = Namespace(
        name="testcharm",
        revision=7,
        channel=["channel1", "channel2", "channel3"],
        resource=[],
    )
    ReleaseCommand("group", config).run(args)

    expected = "Revision 7 of charm 'testcharm' released to channel1, channel2, channel3"
    assert [expected] == [rec.message for rec in caplog.records]


def test_release_including_resources(caplog, store_mock, config):
    """Releasing with resources."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    r1 = ResourceOption(name="foo", revision=3)
    r2 = ResourceOption(name="bar", revision=17)
    args = Namespace(name="testcharm", revision=7, channel=["testchannel"], resource=[r1, r2])
    ReleaseCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.release("testcharm", 7, ["testchannel"], [r1, r2]),
    ]

    expected = (
        "Revision 7 of charm 'testcharm' released to testchannel "
        "(attaching resources: 'foo' r3, 'bar' r17)"
    )
    assert [expected] == [rec.message for rec in caplog.records]


def test_release_options_resource(config):
    """The --resource-file option implies a set of validations."""
    cmd = ReleaseCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "resource"]
    assert isinstance(action.type, ResourceOption)


@pytest.mark.parametrize(
    "sysargs,expected_parsed",
    [
        (
            ["somename", "--channel=stable", "--revision=33"],
            ("somename", 33, ["stable"], []),
        ),
        (
            ["somename", "--channel=stable", "-r", "33"],
            ("somename", 33, ["stable"], []),
        ),
        (
            ["somename", "-c", "stable", "--revision=33"],
            ("somename", 33, ["stable"], []),
        ),
        (
            ["-c", "stable", "--revision=33", "somename"],
            ("somename", 33, ["stable"], []),
        ),
        (
            ["-c", "beta", "--revision=1", "--channel=edge", "name"],
            ("name", 1, ["beta", "edge"], []),
        ),
        (
            ["somename", "-c=beta", "-r=3", "--resource=foo:15"],
            ("somename", 3, ["beta"], [ResourceOption("foo", 15)]),
        ),
        (
            ["somename", "-c=beta", "-r=3", "--resource=foo:15", "--resource=bar:99"],
            (
                "somename",
                3,
                ["beta"],
                [ResourceOption("foo", 15), ResourceOption("bar", 99)],
            ),
        ),
    ],
)
def test_release_parameters_ok(config, sysargs, expected_parsed):
    """Control of different combination of sane parameters."""
    cmd = ReleaseCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    try:
        args = parser.parse_args(sysargs)
    except SystemExit:
        pytest.fail("Parsing of {} was not ok.".format(sysargs))
    attribs = ["name", "revision", "channel", "resource"]
    assert args == Namespace(**dict(zip(attribs, expected_parsed)))


@pytest.mark.parametrize(
    "sysargs",
    [
        ["somename", "--channel=stable", "--revision=foo"],  # revision not an int
        ["somename", "--channel=stable"],  # missing the revision
        ["somename", "--revision=1"],  # missing a channel
        [
            "somename",
            "--channel=stable",
            "--revision=1",
            "--revision=2",
        ],  # too many revisions
        ["--channel=stable", "--revision=1"],  # missing the name
        ["somename", "-c=beta", "-r=3", "--resource=foo15"],  # bad resource format
    ],
)
def test_release_parameters_bad(config, sysargs):
    """Control of different option/parameters combinations that are not valid."""
    cmd = ReleaseCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(sysargs)


# -- tests for the status command


def _build_channels(track="latest"):
    """Helper to build simple channels structure."""
    channels = []
    risks = ["stable", "candidate", "beta", "edge"]
    for risk, fback in zip(risks, [None] + risks):
        name = "/".join((track, risk))
        fallback = None if fback is None else "/".join((track, fback))
        channels.append(Channel(name=name, fallback=fallback, track=track, risk=risk, branch=None))
    return channels


def _build_revision(revno, version):
    """Helper to build a revision."""
    return Revision(
        revision=revno,
        version=version,
        created_at=datetime.datetime(2020, 7, 3, 20, 30, 40),
        status="accepted",
        errors=[],
        bases=[Base(architecture="amd64", channel="20.04", name="ubuntu")],
    )


def _build_release(revision, channel, expires_at=None, resources=None, base=None):
    """Helper to build a release."""
    if resources is None:
        resources = []
    if base is None:
        base = Base(architecture="amd64", channel="20.04", name="ubuntu")
    return Release(
        revision=revision,
        channel=channel,
        expires_at=expires_at,
        resources=resources,
        base=base,
    )


def test_status_simple_ok(caplog, store_mock, config):
    """Simple happy case of getting a status."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channel_map = [
        _build_release(revision=7, channel="latest/stable"),
        _build_release(revision=7, channel="latest/candidate"),
        _build_release(revision=80, channel="latest/beta"),
        _build_release(revision=156, channel="latest/edge"),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=7, version="v7"),
        _build_revision(revno=80, version="2.0"),
        _build_revision(revno=156, version="git-0db35ea1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version       Revision",
        "latest   ubuntu 20.04 (amd64)  stable     v7            7",
        "                               candidate  v7            7",
        "                               beta       2.0           80",
        "                               edge       git-0db35ea1  156",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_empty(caplog, store_mock, config):
    """Empty response from the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.list_releases.return_value = [], [], []
    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    expected = "Nothing has been released yet."
    assert [expected] == [rec.message for rec in caplog.records]


def test_status_channels_not_released_with_fallback(caplog, store_mock, config):
    """Support gaps in channel releases, having fallbacks."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channel_map = [
        _build_release(revision=7, channel="latest/stable"),
        _build_release(revision=80, channel="latest/edge"),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=7, version="v7"),
        _build_revision(revno=80, version="2.0"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version    Revision",
        "latest   ubuntu 20.04 (amd64)  stable     v7         7",
        "                               candidate  ↑          ↑",
        "                               beta       ↑          ↑",
        "                               edge       2.0        80",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_channels_not_released_without_fallback(caplog, store_mock, config):
    """Support gaps in channel releases, nothing released in more stable ones."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channel_map = [
        _build_release(revision=5, channel="latest/beta"),
        _build_release(revision=12, channel="latest/edge"),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=5, version="5.1"),
        _build_revision(revno=12, version="almostready"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version      Revision",
        "latest   ubuntu 20.04 (amd64)  stable     -            -",
        "                               candidate  -            -",
        "                               beta       5.1          5",
        "                               edge       almostready  12",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_multiple_tracks(caplog, store_mock, config):
    """Support multiple tracks."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channel_map = [
        _build_release(revision=503, channel="latest/stable"),
        _build_release(revision=1, channel="2.0/edge"),
    ]
    channels_latest = _build_channels()
    channels_track = _build_channels(track="2.0")
    channels = channels_latest + channels_track
    revisions = [
        _build_revision(revno=503, version="7.5.3"),
        _build_revision(revno=1, version="1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version    Revision",
        "latest   ubuntu 20.04 (amd64)  stable     7.5.3      503",
        "                               candidate  ↑          ↑",
        "                               beta       ↑          ↑",
        "                               edge       ↑          ↑",
        "2.0      ubuntu 20.04 (amd64)  stable     -          -",
        "                               candidate  -          -",
        "                               beta       -          -",
        "                               edge       1          1",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_tracks_order(caplog, store_mock, config):
    """Respect the track ordering from the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    channel_map = [
        _build_release(revision=1, channel="latest/edge"),
        _build_release(revision=2, channel="aaa/edge"),
        _build_release(revision=3, channel="2.0/edge"),
        _build_release(revision=4, channel="zzz/edge"),
    ]
    channels_latest = _build_channels()
    channels_track_1 = _build_channels(track="zzz")
    channels_track_2 = _build_channels(track="2.0")
    channels_track_3 = _build_channels(track="aaa")
    channels = channels_latest + channels_track_1 + channels_track_2 + channels_track_3
    revisions = [
        _build_revision(revno=1, version="v1"),
        _build_revision(revno=2, version="v2"),
        _build_revision(revno=3, version="v3"),
        _build_revision(revno=4, version="v4"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version    Revision",
        "latest   ubuntu 20.04 (amd64)  stable     -          -",
        "                               candidate  -          -",
        "                               beta       -          -",
        "                               edge       v1         1",
        "zzz      ubuntu 20.04 (amd64)  stable     -          -",
        "                               candidate  -          -",
        "                               beta       -          -",
        "                               edge       v4         4",
        "2.0      ubuntu 20.04 (amd64)  stable     -          -",
        "                               candidate  -          -",
        "                               beta       -          -",
        "                               edge       v3         3",
        "aaa      ubuntu 20.04 (amd64)  stable     -          -",
        "                               candidate  -          -",
        "                               beta       -          -",
        "                               edge       v2         2",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_with_one_branch(caplog, store_mock, config):
    """Support having one branch."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    tstamp_with_timezone = dateutil.parser.parse("2020-07-03T20:30:40Z")
    channel_map = [
        _build_release(revision=5, channel="latest/beta"),
        _build_release(
            revision=12,
            channel="latest/beta/mybranch",
            expires_at=tstamp_with_timezone,
        ),
    ]
    channels = _build_channels()
    channels.append(
        Channel(
            name="latest/beta/mybranch",
            fallback="latest/beta",
            track="latest",
            risk="beta",
            branch="mybranch",
        )
    )
    revisions = [
        _build_revision(revno=5, version="5.1"),
        _build_revision(revno=12, version="ver.12"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel        Version    Revision    Expires at",
        "latest   ubuntu 20.04 (amd64)  stable         -          -",
        "                               candidate      -          -",
        "                               beta           5.1        5",
        "                               edge           ↑          ↑",
        "                               beta/mybranch  ver.12     12          2020-07-03T20:30:40+00:00",  # NOQA
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_with_multiple_branches(caplog, store_mock, config):
    """Support having multiple branches."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    tstamp = dateutil.parser.parse("2020-07-03T20:30:40Z")
    channel_map = [
        _build_release(revision=5, channel="latest/beta"),
        _build_release(revision=12, channel="latest/beta/branch-1", expires_at=tstamp),
        _build_release(revision=15, channel="latest/beta/branch-2", expires_at=tstamp),
    ]
    channels = _build_channels()
    channels.extend(
        [
            Channel(
                name="latest/beta/branch-1",
                fallback="latest/beta",
                track="latest",
                risk="beta",
                branch="branch-1",
            ),
            Channel(
                name="latest/beta/branch-2",
                fallback="latest/beta",
                track="latest",
                risk="beta",
                branch="branch-2",
            ),
        ]
    )
    revisions = [
        _build_revision(revno=5, version="5.1"),
        _build_revision(revno=12, version="ver.12"),
        _build_revision(revno=15, version="15.0.0"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel        Version    Revision    Expires at",
        "latest   ubuntu 20.04 (amd64)  stable         -          -",
        "                               candidate      -          -",
        "                               beta           5.1        5",
        "                               edge           ↑          ↑",
        "                               beta/branch-1  ver.12     12          2020-07-03T20:30:40+00:00",  # NOQA
        "                               beta/branch-2  15.0.0     15          2020-07-03T20:30:40+00:00",  # NOQA
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_with_resources(caplog, store_mock, config):
    """Support having multiple branches."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    res1 = Resource(name="resource1", optional=True, revision=1, resource_type="file")
    res2 = Resource(name="resource2", optional=True, revision=54, resource_type="file")
    channel_map = [
        _build_release(revision=5, channel="latest/candidate", resources=[res1, res2]),
        _build_release(revision=5, channel="latest/beta", resources=[res1]),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=5, version="5.1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    expected = [
        "Track    Base                  Channel    Version    Revision    Resources",
        "latest   ubuntu 20.04 (amd64)  stable     -          -           -",
        "                               candidate  5.1        5           resource1 (r1), resource2 (r54)",  # NOQA
        "                               beta       5.1        5           resource1 (r1)",
        "                               edge       ↑          ↑           ↑",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_with_resources_missing_after_closed_channel(caplog, store_mock, config):
    """Specific glitch for a channel without resources after a closed one."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    resource = Resource(name="resource", optional=True, revision=1, resource_type="file")
    channel_map = [
        _build_release(revision=5, channel="latest/stable", resources=[resource]),
        _build_release(revision=5, channel="latest/beta", resources=[]),
        _build_release(revision=5, channel="latest/edge", resources=[resource]),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=5, version="5.1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    expected = [
        "Track    Base                  Channel    Version    Revision    Resources",
        "latest   ubuntu 20.04 (amd64)  stable     5.1        5           resource (r1)",
        "                               candidate  ↑          ↑           ↑",
        "                               beta       5.1        5           -",
        "                               edge       5.1        5           resource (r1)",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_with_resources_and_branches(caplog, store_mock, config):
    """Support having multiple branches."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    tstamp = dateutil.parser.parse("2020-07-03T20:30:40Z")
    res1 = Resource(name="testres", optional=True, revision=1, resource_type="file")
    res2 = Resource(name="testres", optional=True, revision=14, resource_type="file")
    channel_map = [
        _build_release(revision=23, channel="latest/beta", resources=[res2]),
        _build_release(
            revision=5,
            channel="latest/edge/mybranch",
            expires_at=tstamp,
            resources=[res1],
        ),
    ]
    channels = _build_channels()
    channels.append(
        Channel(
            name="latest/edge/mybranch",
            fallback="latest/edge",
            track="latest",
            risk="edge",
            branch="mybranch",
        )
    )
    revisions = [
        _build_revision(revno=5, version="5.1"),
        _build_revision(revno=23, version="7.0.0"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    expected = [
        "Track    Base                  Channel        Version    Revision    Resources      Expires at",  # NOQA
        "latest   ubuntu 20.04 (amd64)  stable         -          -           -",
        "                               candidate      -          -           -",
        "                               beta           7.0.0      23          testres (r14)",
        "                               edge           ↑          ↑           ↑",
        "                               edge/mybranch  5.1        5           testres (r1)   2020-07-03T20:30:40+00:00",  # NOQA
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_multiplebases_single_track(caplog, store_mock, config):
    """Multiple bases with one track."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    other_base = Base(architecture="16b", channel="1", name="xz")
    channel_map = [
        _build_release(revision=7, channel="latest/stable", base=other_base),
        _build_release(revision=7, channel="latest/candidate"),
        _build_release(revision=80, channel="latest/beta", base=other_base),
        _build_release(revision=156, channel="latest/edge"),
    ]
    channels = _build_channels()
    revisions = [
        _build_revision(revno=7, version="v7"),
        _build_revision(revno=80, version="2.0"),
        _build_revision(revno=156, version="git-0db35ea1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version       Revision",
        "latest   ubuntu 20.04 (amd64)  stable     -             -",
        "                               candidate  v7            7",
        "                               beta       ↑             ↑",
        "                               edge       git-0db35ea1  156",
        "         xz 1 (16b)            stable     v7            7",
        "                               candidate  ↑             ↑",
        "                               beta       2.0           80",
        "                               edge       ↑             ↑",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_multiplebases_multiple_tracks(caplog, store_mock, config):
    """Multiple bases with several tracks."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    other_base = Base(architecture="16b", channel="1", name="xz")
    channel_map = [
        _build_release(revision=7, channel="latest/stable", base=other_base),
        _build_release(revision=7, channel="latest/candidate"),
        _build_release(revision=80, channel="latest/beta", base=other_base),
        _build_release(revision=156, channel="latest/edge"),
        _build_release(revision=7, channel="2.0/stable", base=other_base),
        _build_release(revision=7, channel="2.0/candidate"),
        _build_release(revision=80, channel="2.0/beta", base=other_base),
        _build_release(revision=156, channel="2.0/edge"),
        _build_release(revision=156, channel="3.0/edge"),
    ]
    channels = _build_channels() + _build_channels(track="2.0") + _build_channels(track="3.0")
    revisions = [
        _build_revision(revno=7, version="v7"),
        _build_revision(revno=80, version="2.0"),
        _build_revision(revno=156, version="git-0db35ea1"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel    Version       Revision",
        "latest   ubuntu 20.04 (amd64)  stable     -             -",
        "                               candidate  v7            7",
        "                               beta       ↑             ↑",
        "                               edge       git-0db35ea1  156",
        "         xz 1 (16b)            stable     v7            7",
        "                               candidate  ↑             ↑",
        "                               beta       2.0           80",
        "                               edge       ↑             ↑",
        "2.0      ubuntu 20.04 (amd64)  stable     -             -",
        "                               candidate  v7            7",
        "                               beta       ↑             ↑",
        "                               edge       git-0db35ea1  156",
        "         xz 1 (16b)            stable     v7            7",
        "                               candidate  ↑             ↑",
        "                               beta       2.0           80",
        "                               edge       ↑             ↑",
        "3.0      ubuntu 20.04 (amd64)  stable     -             -",
        "                               candidate  -             -",
        "                               beta       -             -",
        "                               edge       git-0db35ea1  156",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_status_multiplebases_everything_combined(caplog, store_mock, config):
    """Multiple bases with several other modifiers, just a sanity check."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    other_base = Base(architecture="16b", channel="1", name="xz")
    tstamp = dateutil.parser.parse("2020-07-03T20:30:40Z")
    resource = Resource(name="testres", optional=True, revision=1, resource_type="file")
    channel_map = [
        _build_release(revision=7, channel="latest/candidate"),
        _build_release(revision=156, channel="latest/edge"),
        _build_release(revision=7, channel="latest/candidate/br1", expires_at=tstamp),
        _build_release(revision=7, channel="latest/stable", base=other_base),
        _build_release(revision=80, channel="latest/beta", base=other_base),
        _build_release(
            revision=99,
            channel="latest/beta/br2",
            base=other_base,
            expires_at=tstamp,
            resources=[resource],
        ),
        _build_release(revision=7, channel="2.0/candidate"),
        _build_release(revision=80, channel="2.0/beta"),
        _build_release(revision=7, channel="2.0/stable", base=other_base),
        _build_release(revision=80, channel="2.0/edge", base=other_base),
        _build_release(revision=80, channel="2.0/edge/foobar", base=other_base, expires_at=tstamp),
    ]
    channels = _build_channels() + _build_channels(track="2.0")
    channels.extend(
        [
            Channel(
                name="latest/candidate/br1",
                fallback="latest/candidate",
                track="latest",
                risk="candidate",
                branch="br1",
            ),
            Channel(
                name="latest/beta/br2",
                fallback="latest/beta",
                track="latest",
                risk="beta",
                branch="br2",
            ),
            Channel(
                name="2.0/edge/foobar",
                fallback="2.0/edge",
                track="2.0",
                risk="edge",
                branch="foobar",
            ),
        ]
    )
    revisions = [
        _build_revision(revno=7, version="v7"),
        _build_revision(revno=80, version="2.0"),
        _build_revision(revno=156, version="git-0db35ea1"),
        _build_revision(revno=99, version="weird"),
    ]
    store_mock.list_releases.return_value = (channel_map, channels, revisions)

    args = Namespace(name="testcharm")
    StatusCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_releases("testcharm"),
    ]

    expected = [
        "Track    Base                  Channel        Version       Revision    Resources     Expires at",  # NOQA
        "latest   ubuntu 20.04 (amd64)  stable         -             -           -",
        "                               candidate      v7            7           -",
        "                               beta           ↑             ↑           ↑",
        "                               edge           git-0db35ea1  156         -",
        "                               candidate/br1  v7            7           -             2020-07-03T20:30:40+00:00",  # NOQA
        "         xz 1 (16b)            stable         v7            7           -",
        "                               candidate      ↑             ↑           ↑",
        "                               beta           2.0           80          -",
        "                               edge           ↑             ↑           ↑",
        "                               beta/br2       weird         99          testres (r1)  2020-07-03T20:30:40+00:00",  # NOQA
        "2.0      ubuntu 20.04 (amd64)  stable         -             -           -",
        "                               candidate      v7            7           -",
        "                               beta           2.0           80          -",
        "                               edge           ↑             ↑           ↑",
        "         xz 1 (16b)            stable         v7            7           -",
        "                               candidate      ↑             ↑           ↑",
        "                               beta           ↑             ↑           ↑",
        "                               edge           2.0           80          -",
        "                               edge/foobar    2.0           80          -             2020-07-03T20:30:40+00:00",  # NOQA
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for create library command


def test_createlib_simple(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path with result from the Store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    store_mock.create_library_id.return_value = lib_id

    args = Namespace(name="testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        CreateLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.create_library_id("testcharm", "testlib"),
    ]
    expected = [
        "Library charms.testcharm.v0.testlib created with id test-example-lib-id.",
        "Consider 'git add lib/charms/testcharm/v0/testlib.py'.",
    ]
    assert expected == [rec.message for rec in caplog.records]
    created_lib_file = tmp_path / "lib" / "charms" / "testcharm" / "v0" / "testlib.py"

    env = get_templates_environment("charmlibs")
    expected_newlib_content = env.get_template("new_library.py.j2").render(lib_id=lib_id)
    assert created_lib_file.read_text() == expected_newlib_content


def test_createlib_name_from_metadata_problem(store_mock, config):
    """The metadata wasn't there to get the name."""
    args = Namespace(name="testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = None
        with pytest.raises(CommandError) as cm:
            CreateLibCommand("group", config).run(args)
        assert str(cm.value) == (
            "Cannot find a valid charm name in metadata.yaml. Check you are in a charm "
            "directory with metadata.yaml."
        )


def test_createlib_name_contains_dash(caplog, store_mock, tmp_path, monkeypatch, config):
    """'-' is valid in charm names but can't be imported"""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    store_mock.create_library_id.return_value = lib_id

    args = Namespace(name="testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "test-charm"
        CreateLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.create_library_id("test-charm", "testlib"),
    ]
    expected = [
        "Library charms.test_charm.v0.testlib created with id test-example-lib-id.",
        "Consider 'git add lib/charms/test_charm/v0/testlib.py'.",
    ]
    assert expected == [rec.message for rec in caplog.records]
    created_lib_file = tmp_path / "lib" / "charms" / "test_charm" / "v0" / "testlib.py"

    env = get_templates_environment("charmlibs")
    expected_newlib_content = env.get_template("new_library.py.j2").render(lib_id=lib_id)
    assert created_lib_file.read_text() == expected_newlib_content


@pytest.mark.parametrize(
    "lib_name",
    [
        "foo.bar",
        "foo/bar",
        "Foo",
        "123foo",
        "_foo",
        "",
    ],
)
def test_createlib_invalid_name(lib_name, config):
    """Verify that it can not be used with an invalid name."""
    args = Namespace(name=lib_name)
    with pytest.raises(CommandError) as err:
        CreateLibCommand("group", config).run(args)
    assert str(err.value) == (
        "Invalid library name. Must only use lowercase alphanumeric "
        "characters and underscore, starting with alpha."
    )


def test_createlib_path_already_there(tmp_path, monkeypatch, config):
    """The intended-to-be-created library is already there."""
    monkeypatch.chdir(tmp_path)

    factory.create_lib_filepath("test-charm-name", "testlib", api=0)
    args = Namespace(name="testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "test-charm-name"
        with pytest.raises(CommandError) as err:
            CreateLibCommand("group", config).run(args)

    assert str(err.value) == (
        "This library already exists: 'lib/charms/test_charm_name/v0/testlib.py'."
    )


def test_createlib_path_can_not_write(tmp_path, monkeypatch, store_mock, add_cleanup, config):
    """Disk error when trying to write the new lib (bad permissions, name too long, whatever)."""
    lib_dir = tmp_path / "lib" / "charms" / "test_charm_name" / "v0"
    lib_dir.mkdir(parents=True)
    lib_dir.chmod(0o111)
    add_cleanup(lib_dir.chmod, 0o777)
    monkeypatch.chdir(tmp_path)

    args = Namespace(name="testlib")
    store_mock.create_library_id.return_value = "lib_id"
    expected_error = "Error writing the library in .*: PermissionError.*"
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "test-charm-name"
        with pytest.raises(CommandError, match=expected_error):
            CreateLibCommand("group", config).run(args)


def test_createlib_library_template_is_python(caplog, store_mock, tmp_path, monkeypatch):
    """Verify that the template used to create a library is valid Python code."""
    env = get_templates_environment("charmlibs")
    newlib_content = env.get_template("new_library.py.j2").render(lib_id="test-lib-id")
    compile(newlib_content, "test.py", "exec")


# -- tests for publish libraries command


def test_publishlib_simple(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path publishing because no revision at all in the Store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "testcharm", "testlib", api=0, patch=1, lib_id=lib_id
    )

    store_mock.get_libraries_tips.return_value = {}
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
        call.create_library_revision("testcharm", lib_id, 0, 1, content, content_hash),
    ]
    expected = "Library charms.testcharm.v0.testlib sent to the store with version 0.1"
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_contains_dash(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path publishing because no revision at all in the Store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "test-charm", "testlib", api=0, patch=1, lib_id=lib_id
    )

    store_mock.get_libraries_tips.return_value = {}
    args = Namespace(library="charms.test_charm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "test-charm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
        call.create_library_revision("test-charm", lib_id, 0, 1, content, content_hash),
    ]
    expected = "Library charms.test_charm.v0.testlib sent to the store with version 0.1"
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_all(caplog, store_mock, tmp_path, monkeypatch, config):
    """Publish all the libraries found in disk."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    c1, h1 = factory.create_lib_filepath(
        "testcharm-1", "testlib-a", api=0, patch=1, lib_id="lib_id_1"
    )
    c2, h2 = factory.create_lib_filepath(
        "testcharm-1", "testlib-b", api=0, patch=1, lib_id="lib_id_2"
    )
    c3, h3 = factory.create_lib_filepath(
        "testcharm-1", "testlib-b", api=1, patch=3, lib_id="lib_id_3"
    )
    factory.create_lib_filepath("testcharm-2", "testlib", api=0, patch=1, lib_id="lib_id_4")

    store_mock.get_libraries_tips.return_value = {}
    args = Namespace(library=None)
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm-1"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips(
            [
                {"lib_id": "lib_id_1", "api": 0},
                {"lib_id": "lib_id_2", "api": 0},
                {"lib_id": "lib_id_3", "api": 1},
            ]
        ),
        call.create_library_revision("testcharm-1", "lib_id_1", 0, 1, c1, h1),
        call.create_library_revision("testcharm-1", "lib_id_2", 0, 1, c2, h2),
        call.create_library_revision("testcharm-1", "lib_id_3", 1, 3, c3, h3),
    ]
    names = [
        "charms.testcharm_1.v0.testlib-a",
        "charms.testcharm_1.v0.testlib-b",
        "charms.testcharm_1.v1.testlib-b",
    ]
    expected = [
        "Libraries found under 'lib/charms/testcharm_1': " + str(names),
        "Library charms.testcharm_1.v0.testlib-a sent to the store with version 0.1",
        "Library charms.testcharm_1.v0.testlib-b sent to the store with version 0.1",
        "Library charms.testcharm_1.v1.testlib-b sent to the store with version 1.3",
    ]
    records = [rec.message for rec in caplog.records]
    assert all(e in records for e in expected)


def test_publishlib_not_found(caplog, store_mock, tmp_path, monkeypatch, config):
    """The indicated library is not found."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        with pytest.raises(CommandError) as cm:
            PublishLibCommand("group", config).run(args)

        assert str(cm.value) == (
            "The specified library was not found at path 'lib/charms/testcharm/v0/testlib.py'."
        )


def test_publishlib_not_from_current_charm(caplog, store_mock, tmp_path, monkeypatch, config):
    """The indicated library to publish does not belong to this charm."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)
    factory.create_lib_filepath("testcharm", "testlib", api=0)

    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "charm2"
        with pytest.raises(CommandError) as cm:
            PublishLibCommand("group", config).run(args)

        assert str(cm.value) == (
            "The library charms.testcharm.v0.testlib does not belong to this charm 'charm2'."
        )


def test_publishlib_name_from_metadata_problem(store_mock, config):
    """The metadata wasn't there to get the name."""
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = None
        with pytest.raises(CommandError) as cm:
            PublishLibCommand("group", config).run(args)

        assert str(cm.value) == (
            "Can't access name in 'metadata.yaml' file. The 'publish-lib' command needs to "
            "be executed in a valid project's directory."
        )


def test_publishlib_store_is_advanced(caplog, store_mock, tmp_path, monkeypatch, config):
    """The store has a higher revision number than what we expect."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    factory.create_lib_filepath("testcharm", "testlib", api=0, patch=1, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=2,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = (
        "Library charms.testcharm.v0.testlib is out-of-date locally, Charmhub has version 0.2, "
        "please fetch the updates before publishing."
    )
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_store_is_exactly_behind_ok(caplog, store_mock, tmp_path, monkeypatch, config):
    """The store is exactly one revision less than local lib, ok."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "testcharm", "testlib", api=0, patch=7, lib_id=lib_id
    )

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=6,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
        call.create_library_revision("testcharm", lib_id, 0, 7, content, content_hash),
    ]
    expected = "Library charms.testcharm.v0.testlib sent to the store with version 0.7"
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_store_is_exactly_behind_same_hash(
    caplog, store_mock, tmp_path, monkeypatch, config
):
    """The store is exactly one revision less than local lib, same hash."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "testcharm", "testlib", api=0, patch=7, lib_id=lib_id
    )

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash=content_hash,
            api=0,
            patch=6,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = (
        "Library charms.testcharm.v0.testlib LIBPATCH number was incorrectly incremented, "
        "Charmhub has the same content in version 0.6."
    )
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_store_is_too_behind(caplog, store_mock, tmp_path, monkeypatch, config):
    """The store is way more behind than what we expected (local lib too high!)."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    factory.create_lib_filepath("testcharm", "testlib", api=0, patch=4, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=2,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = (
        "Library charms.testcharm.v0.testlib has a wrong LIBPATCH number, it's too high, Charmhub "
        "highest version is 0.2."
    )
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_store_has_same_revision_same_hash(
    caplog, store_mock, tmp_path, monkeypatch, config
):
    """The store has the same revision we want to publish, with the same hash."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "testcharm", "testlib", api=0, patch=7, lib_id=lib_id
    )

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash=content_hash,
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = "Library charms.testcharm.v0.testlib is already updated in Charmhub."
    assert [expected] == [rec.message for rec in caplog.records]


def test_publishlib_store_has_same_revision_other_hash(
    caplog, store_mock, tmp_path, monkeypatch, config
):
    """The store has the same revision we want to publish, but with a different hash."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    factory.create_lib_filepath("testcharm", "testlib", api=0, patch=7, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(library="charms.testcharm.v0.testlib")
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        PublishLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = (
        "Library charms.testcharm.v0.testlib version 0.7 is the same than in Charmhub but "
        "content is different"
    )
    assert [expected] == [rec.message for rec in caplog.records]


# -- tests for _get_lib_info helper


def _create_lib(extra_content=None, metadata_id=None, metadata_api=None, metadata_patch=None):
    """Helper to create the structures on disk for a given lib.

    WARNING: this function has the capability of creating INCORRECT structures on disk.

    This is specific for the _get_lib_info tests below, other tests should use the
    functionality provided by the factory.
    """
    base_dir = pathlib.Path("lib")
    lib_file = base_dir / "charms" / "testcharm" / "v3" / "testlib.py"
    lib_file.parent.mkdir(parents=True, exist_ok=True)

    # save the content to that specific file under custom structure
    if metadata_id is None:
        metadata_id = "LIBID = 'test-lib-id'"
    if metadata_api is None:
        metadata_api = "LIBAPI = 3"
    if metadata_patch is None:
        metadata_patch = "LIBPATCH = 14"

    fields = [metadata_id, metadata_api, metadata_patch]
    with lib_file.open("wt", encoding="utf8") as fh:
        for f in fields:
            if f:
                fh.write(f + "\n")
        if extra_content:
            fh.write(extra_content)

    return lib_file


def test_getlibinfo_success_simple(tmp_path, monkeypatch):
    """Simple basic case of success getting info from the library."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib()

    lib_data = _get_lib_info(lib_path=test_path)
    assert lib_data.lib_id == "test-lib-id"
    assert lib_data.api == 3
    assert lib_data.patch == 14
    assert lib_data.content_hash is not None
    assert lib_data.content is not None
    assert lib_data.full_name == "charms.testcharm.v3.testlib"
    assert lib_data.path == test_path
    assert lib_data.lib_name == "testlib"
    assert lib_data.charm_name == "testcharm"


def test_getlibinfo_success_content(tmp_path, monkeypatch):
    """Check that content and its hash are ok."""
    monkeypatch.chdir(tmp_path)
    extra_content = """
        extra lines for the file
        extra non-ascii, for sanity: ñáéíóú
        the content is everything, this plus metadata
        the hash should be of this, excluding metadata
    """
    test_path = _create_lib(extra_content=extra_content)

    lib_data = _get_lib_info(lib_path=test_path)
    assert lib_data.content == test_path.read_text()
    assert lib_data.content_hash == hashlib.sha256(extra_content.encode("utf8")).hexdigest()


@pytest.mark.parametrize(
    "name",
    [
        "charms.testcharm.v3.testlib.py",
        "charms.testcharm.testlib",
        "testcharm.v2.testlib",
        "mycharms.testcharm.v2.testlib",
    ],
)
def test_getlibinfo_bad_name(name):
    """Different combinations of a bad library name."""
    with pytest.raises(CommandError) as err:
        _get_lib_info(full_name=name)
    assert str(err.value) == (
        "Charm library name {!r} must conform to charms.<charm>.vN.<libname>".format(name)
    )


@pytest.mark.parametrize(
    "path",
    [
        "charms/testcharm/v3/testlib",
        "charms/testcharm/v3/testlib.html",
        "charms/testcharm/v3/testlib.",
        "charms/testcharm/testlib.py",
        "testcharm/v2/testlib.py",
        "mycharms/testcharm/v2/testlib.py",
    ],
)
def test_getlibinfo_bad_path(path):
    """Different combinations of a bad library path."""
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=pathlib.Path(path))
    assert str(err.value) == (
        "Charm library path {} must conform to lib/charms/<charm>/vN/<libname>.py".format(path)
    )


@pytest.mark.parametrize(
    "name",
    [
        "charms.testcharm.v-three.testlib",
        "charms.testcharm.v-3.testlib",
        "charms.testcharm.3.testlib",
        "charms.testcharm.vX.testlib",
    ],
)
def test_getlibinfo_bad_api(name):
    """Different combinations of a bad api in the path/name."""
    with pytest.raises(CommandError) as err:
        _get_lib_info(full_name=name)
    assert str(err.value) == (
        "The API version in the library path must be 'vN' where N is an integer."
    )


def test_getlibinfo_missing_library_from_name():
    """Partial case for when the library is not found in disk, starting from the name."""
    test_name = "charms.testcharm.v3.testlib"
    # no create lib!
    lib_data = _get_lib_info(full_name=test_name)
    assert lib_data.lib_id is None
    assert lib_data.api == 3
    assert lib_data.patch == -1
    assert lib_data.content_hash is None
    assert lib_data.content is None
    assert lib_data.full_name == test_name
    assert lib_data.path == pathlib.Path("lib") / "charms" / "testcharm" / "v3" / "testlib.py"
    assert lib_data.lib_name == "testlib"
    assert lib_data.charm_name == "testcharm"


def test_getlibinfo_missing_library_from_path():
    """Partial case for when the library is not found in disk, starting from the path."""
    test_path = pathlib.Path("lib") / "charms" / "testcharm" / "v3" / "testlib.py"
    # no create lib!
    lib_data = _get_lib_info(lib_path=test_path)
    assert lib_data.lib_id is None
    assert lib_data.api == 3
    assert lib_data.patch == -1
    assert lib_data.content_hash is None
    assert lib_data.content is None
    assert lib_data.full_name == "charms.testcharm.v3.testlib"
    assert lib_data.path == test_path
    assert lib_data.lib_name == "testlib"
    assert lib_data.charm_name == "testcharm"


def test_getlibinfo_malformed_metadata_field(tmp_path, monkeypatch):
    """Some metadata field is not really valid."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_id="LIBID = foo = 23")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == r"Bad metadata line in {!r}: b'LIBID = foo = 23\n'".format(
        str(test_path)
    )


def test_getlibinfo_missing_metadata_field(tmp_path, monkeypatch):
    """Some metadata field is not present."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_patch="", metadata_api="")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} is missing the mandatory metadata fields: LIBAPI, LIBPATCH.".format(
            str(test_path)
        )
    )


def test_getlibinfo_api_not_int(tmp_path, monkeypatch):
    """The API is not an integer."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_api="LIBAPI = v3")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBAPI is not zero or a positive integer.".format(
            str(test_path)
        )
    )


def test_getlibinfo_api_negative(tmp_path, monkeypatch):
    """The API is not negative."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_api="LIBAPI = -3")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBAPI is not zero or a positive integer.".format(
            str(test_path)
        )
    )


def test_getlibinfo_patch_not_int(tmp_path, monkeypatch):
    """The PATCH is not an integer."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_patch="LIBPATCH = beta3")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBPATCH is not zero or a positive integer.".format(
            str(test_path)
        )
    )


def test_getlibinfo_patch_negative(tmp_path, monkeypatch):
    """The PATCH is not negative."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_patch="LIBPATCH = -1")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBPATCH is not zero or a positive integer.".format(
            str(test_path)
        )
    )


def test_getlibinfo_api_patch_both_zero(tmp_path, monkeypatch):
    """Invalid combination of both API and PATCH being 0."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_patch="LIBPATCH = 0", metadata_api="LIBAPI = 0")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata fields LIBAPI and LIBPATCH cannot both be zero.".format(
            str(test_path)
        )
    )


def test_getlibinfo_metadata_api_different_path_api(tmp_path, monkeypatch):
    """The API value included in the file is different than the one in the path."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_api="LIBAPI = 99")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBAPI is different from the version in the path.".format(
            str(test_path)
        )
    )


def test_getlibinfo_libid_non_string(tmp_path, monkeypatch):
    """The ID is not really a string."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_id="LIBID = 99")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBID must be a non-empty ASCII string.".format(
            str(test_path)
        )
    )


def test_getlibinfo_libid_non_ascii(tmp_path, monkeypatch):
    """The ID is not ASCII."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_id="LIBID = 'moño'")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBID must be a non-empty ASCII string.".format(
            str(test_path)
        )
    )


def test_getlibinfo_libid_empty(tmp_path, monkeypatch):
    """The ID is empty."""
    monkeypatch.chdir(tmp_path)
    test_path = _create_lib(metadata_id="LIBID = ''")
    with pytest.raises(CommandError) as err:
        _get_lib_info(lib_path=test_path)
    assert str(err.value) == (
        "Library {!r} metadata field LIBID must be a non-empty ASCII string.".format(
            str(test_path)
        )
    )


# -- tests for fetch libraries command


def test_fetchlib_simple_downloaded(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path fetching the lib for the first time (downloading it)."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    lib_content = "some test content with uñicode ;)"
    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    store_mock.get_library.return_value = Library(
        lib_id=lib_id,
        content=lib_content,
        content_hash="abc",
        api=0,
        patch=7,
        lib_name="testlib",
        charm_name="testcharm",
    )

    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "testcharm", "lib_name": "testlib", "api": 0}]),
        call.get_library("testcharm", lib_id, 0),
    ]
    expected = "Library charms.testcharm.v0.testlib version 0.7 downloaded."
    assert [expected] == [rec.message for rec in caplog.records]
    saved_file = tmp_path / "lib" / "charms" / "testcharm" / "v0" / "testlib.py"
    assert saved_file.read_text() == lib_content


def test_fetchlib_simple_dash_in_name(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path fetching the lib for the first time (downloading it)."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    lib_content = "some test content with uñicode ;)"
    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="test-charm",
        ),
    }
    store_mock.get_library.return_value = Library(
        lib_id=lib_id,
        content=lib_content,
        content_hash="abc",
        api=0,
        patch=7,
        lib_name="testlib",
        charm_name="test-charm",
    )

    FetchLibCommand("group", config).run(Namespace(library="charms.test_charm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "test-charm", "lib_name": "testlib", "api": 0}]),
        call.get_library("test-charm", lib_id, 0),
    ]
    expected = "Library charms.test_charm.v0.testlib version 0.7 downloaded."
    assert [expected] == [rec.message for rec in caplog.records]
    saved_file = tmp_path / "lib" / "charms" / "test_charm" / "v0" / "testlib.py"
    assert saved_file.read_text() == lib_content


def test_fetchlib_simple_dash_in_name_on_disk(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path fetching the lib for the first time (downloading it)."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    lib_content = "test-content"
    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="test-charm",
        ),
    }
    store_mock.get_library.return_value = Library(
        lib_id=lib_id,
        content=lib_content,
        content_hash="abc",
        api=0,
        patch=7,
        lib_name="testlib",
        charm_name="test-charm",
    )
    factory.create_lib_filepath("test-charm", "testlib", api=0, patch=1, lib_id=lib_id)

    FetchLibCommand("group", config).run(Namespace(library=None))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": "test-example-lib-id", "api": 0}]),
        call.get_library("test-charm", lib_id, 0),
    ]
    expected = "Library charms.test_charm.v0.testlib updated to version 0.7."
    assert [expected] == [rec.message for rec in caplog.records]


def test_fetchlib_simple_updated(caplog, store_mock, tmp_path, monkeypatch, config):
    """Happy path fetching the lib for Nth time (updating it)."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    content, content_hash = factory.create_lib_filepath(
        "testcharm", "testlib", api=0, patch=1, lib_id=lib_id
    )

    new_lib_content = "some test content with uñicode ;)"
    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=2,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    store_mock.get_library.return_value = Library(
        lib_id=lib_id,
        content=new_lib_content,
        content_hash="abc",
        api=0,
        patch=2,
        lib_name="testlib",
        charm_name="testcharm",
    )

    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
        call.get_library("testcharm", lib_id, 0),
    ]
    expected = "Library charms.testcharm.v0.testlib updated to version 0.2."
    assert [expected] == [rec.message for rec in caplog.records]
    saved_file = tmp_path / "lib" / "charms" / "testcharm" / "v0" / "testlib.py"
    assert saved_file.read_text() == new_lib_content


def test_fetchlib_all(caplog, store_mock, tmp_path, monkeypatch, config):
    """Update all the libraries found in disk."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    c1, h1 = factory.create_lib_filepath(
        "testcharm1", "testlib1", api=0, patch=1, lib_id="lib_id_1"
    )
    c2, h2 = factory.create_lib_filepath(
        "testcharm2", "testlib2", api=3, patch=5, lib_id="lib_id_2"
    )

    store_mock.get_libraries_tips.return_value = {
        ("lib_id_1", 0): Library(
            lib_id="lib_id_1",
            content=None,
            content_hash="abc",
            api=0,
            patch=2,
            lib_name="testlib1",
            charm_name="testcharm1",
        ),
        ("lib_id_2", 3): Library(
            lib_id="lib_id_2",
            content=None,
            content_hash="def",
            api=3,
            patch=14,
            lib_name="testlib2",
            charm_name="testcharm2",
        ),
    }
    _store_libs_info = [
        Library(
            lib_id="lib_id_1",
            content="new lib content 1",
            content_hash="xxx",
            api=0,
            patch=2,
            lib_name="testlib1",
            charm_name="testcharm1",
        ),
        Library(
            lib_id="lib_id_2",
            content="new lib content 2",
            content_hash="yyy",
            api=3,
            patch=14,
            lib_name="testlib2",
            charm_name="testcharm2",
        ),
    ]
    store_mock.get_library.side_effect = lambda *a: _store_libs_info.pop(0)

    FetchLibCommand("group", config).run(Namespace(library=None))

    assert store_mock.mock_calls == [
        call.get_libraries_tips(
            [
                {"lib_id": "lib_id_1", "api": 0},
                {"lib_id": "lib_id_2", "api": 3},
            ]
        ),
        call.get_library("testcharm1", "lib_id_1", 0),
        call.get_library("testcharm2", "lib_id_2", 3),
    ]
    names = [
        "charms.testcharm1.v0.testlib1",
        "charms.testcharm2.v3.testlib2",
    ]
    expected = [
        "Libraries found under 'lib/charms': " + str(names),
        "Library charms.testcharm1.v0.testlib1 updated to version 0.2.",
        "Library charms.testcharm2.v3.testlib2 updated to version 3.14.",
    ]

    records = [rec.message for rec in caplog.records]
    assert all(e in records for e in expected)
    saved_file = tmp_path / "lib" / "charms" / "testcharm1" / "v0" / "testlib1.py"
    assert saved_file.read_text() == "new lib content 1"
    saved_file = tmp_path / "lib" / "charms" / "testcharm2" / "v3" / "testlib2.py"
    assert saved_file.read_text() == "new lib content 2"


def test_fetchlib_store_not_found(caplog, store_mock, config):
    """The indicated library is not found in the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.get_libraries_tips.return_value = {}
    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "testcharm", "lib_name": "testlib", "api": 0}]),
    ]
    expected = "Library charms.testcharm.v0.testlib not found in Charmhub."
    assert [expected] == [rec.message for rec in caplog.records]


def test_fetchlib_store_is_old(caplog, store_mock, tmp_path, monkeypatch, config):
    """The store has an older version that what is found locally."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    factory.create_lib_filepath("testcharm", "testlib", api=0, patch=7, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=6,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = "Library charms.testcharm.v0.testlib has local changes, can not be updated."
    assert expected in [rec.message for rec in caplog.records]


def test_fetchlib_store_same_versions_same_hash(caplog, store_mock, tmp_path, monkeypatch, config):
    """The store situation is the same than locally."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    _, c_hash = factory.create_lib_filepath("testcharm", "testlib", api=0, patch=7, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash=c_hash,
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = "Library charms.testcharm.v0.testlib was already up to date in version 0.7."
    assert expected in [rec.message for rec in caplog.records]


def test_fetchlib_store_same_versions_different_hash(
    caplog, store_mock, tmp_path, monkeypatch, config
):
    """The store has the lib in the same version, but with different content."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    monkeypatch.chdir(tmp_path)

    lib_id = "test-example-lib-id"
    factory.create_lib_filepath("testcharm", "testlib", api=0, patch=7, lib_id=lib_id)

    store_mock.get_libraries_tips.return_value = {
        (lib_id, 0): Library(
            lib_id=lib_id,
            content=None,
            content_hash="abc",
            api=0,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    FetchLibCommand("group", config).run(Namespace(library="charms.testcharm.v0.testlib"))

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"lib_id": lib_id, "api": 0}]),
    ]
    expected = "Library charms.testcharm.v0.testlib has local changes, can not be updated."
    assert expected in [rec.message for rec in caplog.records]


# -- tests for list libraries command


def test_listlib_simple(caplog, store_mock, config):
    """Happy path listing simple case."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.get_libraries_tips.return_value = {
        ("some-lib-id", 3): Library(
            lib_id="some-lib-id",
            content=None,
            content_hash="abc",
            api=3,
            patch=7,
            lib_name="testlib",
            charm_name="testcharm",
        ),
    }
    args = Namespace(name="testcharm")
    ListLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "testcharm"}]),
    ]
    expected = [
        "Library name    API    Patch",
        "testlib         3      7",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_listlib_charm_from_metadata(caplog, store_mock, config):
    """Happy path listing simple case."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.get_libraries_tips.return_value = {}
    args = Namespace(name=None)
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = "testcharm"
        ListLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "testcharm"}]),
    ]


def test_listlib_name_from_metadata_problem(store_mock, config):
    """The metadata wasn't there to get the name."""
    args = Namespace(name=None)
    with patch("charmcraft.commands.store.get_name_from_metadata") as mock:
        mock.return_value = None
        with pytest.raises(CommandError) as cm:
            ListLibCommand("group", config).run(args)

        assert str(cm.value) == (
            "Can't access name in 'metadata.yaml' file. The 'list-lib' command must either be "
            "executed from a valid project directory, or specify a charm name using "
            "the --charm-name option."
        )


def test_listlib_empty(caplog, store_mock, config):
    """Nothing found in the store for the specified charm."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.get_libraries_tips.return_value = {}
    args = Namespace(name="testcharm")
    ListLibCommand("group", config).run(args)

    expected = "No libraries found for charm testcharm."
    assert [expected] == [rec.message for rec in caplog.records]


def test_listlib_properly_sorted(caplog, store_mock, config):
    """Check the sorting of the list."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_mock.get_libraries_tips.return_value = {
        ("lib-id-2", 3): Library(
            lib_id="lib-id-1",
            content=None,
            content_hash="abc",
            api=3,
            patch=7,
            lib_name="testlib-2",
            charm_name="testcharm",
        ),
        ("lib-id-2", 2): Library(
            lib_id="lib-id-1",
            content=None,
            content_hash="abc",
            api=2,
            patch=8,
            lib_name="testlib-2",
            charm_name="testcharm",
        ),
        ("lib-id-1", 5): Library(
            lib_id="lib-id-1",
            content=None,
            content_hash="abc",
            api=5,
            patch=124,
            lib_name="testlib-1",
            charm_name="testcharm",
        ),
    }
    args = Namespace(name="testcharm")
    ListLibCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.get_libraries_tips([{"charm_name": "testcharm"}]),
    ]
    expected = [
        "Library name    API    Patch",
        "testlib-1       5      124",
        "testlib-2       2      8",
        "testlib-2       3      7",
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for list resources command


def test_resources_simple(caplog, store_mock, config):
    """Happy path of one result from the Store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        Resource(name="testresource", optional=True, revision=1, resource_type="file"),
    ]
    store_mock.list_resources.return_value = store_response

    args = Namespace(charm_name="testcharm")
    ListResourcesCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_resources("testcharm"),
    ]
    expected = [
        "Charm Rev    Resource      Type    Optional",
        "1            testresource  file    True",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_resources_empty(caplog, store_mock, config):
    """No results from the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = []
    store_mock.list_resources.return_value = store_response

    args = Namespace(charm_name="testcharm")
    ListResourcesCommand("group", config).run(args)

    expected = [
        "No resources associated to testcharm.",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_resources_ordered_and_grouped(caplog, store_mock, config):
    """Results are presented ordered by name in the table."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        Resource(name="bbb-resource", optional=True, revision=2, resource_type="file"),
        Resource(name="ccc-resource", optional=True, revision=1, resource_type="file"),
        Resource(name="bbb-resource", optional=True, revision=3, resource_type="file"),
        Resource(name="aaa-resource", optional=True, revision=2, resource_type="file"),
        Resource(name="bbb-resource", optional=True, revision=5, resource_type="file"),
    ]
    store_mock.list_resources.return_value = store_response

    args = Namespace(charm_name="testcharm")
    ListResourcesCommand("group", config).run(args)

    expected = [
        "Charm Rev    Resource      Type    Optional",
        "5            bbb-resource  file    True",
        "3            bbb-resource  file    True",
        "2            aaa-resource  file    True",
        "             bbb-resource  file    True",
        "1            ccc-resource  file    True",
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for upload resources command


def test_uploadresource_options_filepath_type(config):
    """The --filepath option implies a set of validations."""
    cmd = UploadResourceCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "filepath"]
    assert isinstance(action.type, SingleOptionEnsurer)
    assert action.type.converter is useful_filepath


def test_uploadresource_options_image_type(config):
    """The --image option implies a set of validations."""
    cmd = UploadResourceCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    (action,) = [action for action in parser._actions if action.dest == "image"]
    assert isinstance(action.type, SingleOptionEnsurer)
    assert action.type.converter is str


@pytest.mark.parametrize(
    "sysargs",
    [
        ("c", "r", "--filepath=fpath"),
        ("c", "r", "--image=x"),
    ],
)
def test_uploadresource_options_good_combinations(tmp_path, config, sysargs, monkeypatch):
    """Check the specific rules for filepath and image/[registry] good combinations."""
    # fake the file for filepath
    (tmp_path / "fpath").touch()
    monkeypatch.chdir(tmp_path)

    cmd = UploadResourceCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    try:
        parser.parse_args(sysargs)
    except SystemExit:
        pytest.fail("Argument parsing expected to succeed but failed")


@pytest.mark.parametrize(
    "sysargs",
    [
        ("c", "r"),  # filepath XOR image needs to be specified
        ("c", "r", "--filepath=fpath", "--image=y"),  # can't specify both
    ],
)
def test_uploadresource_options_bad_combinations(config, sysargs, tmp_path, monkeypatch):
    """Check the specific rules for filepath and image/[registry] bad combinations."""
    # fake the file for filepath
    (tmp_path / "fpath").touch()
    monkeypatch.chdir(tmp_path)

    cmd = UploadResourceCommand("group", config)
    parser = ArgumentParser()
    cmd.fill_parser(parser)
    with pytest.raises(SystemExit):
        parsed_args = parser.parse_args(sysargs)
        cmd.parsed_args_post_verification(parser, parsed_args)


def test_uploadresource_filepath_call_ok(caplog, store_mock, config, tmp_path):
    """Simple upload, success result."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    store_response = Uploaded(ok=True, status=200, revision=7, errors=[])
    store_mock.upload_resource.return_value = store_response

    test_resource = tmp_path / "mystuff.bin"
    test_resource.write_text("sample stuff")
    args = Namespace(
        charm_name="mycharm",
        resource_name="myresource",
        filepath=test_resource,
        image=None,
    )
    UploadResourceCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.upload_resource("mycharm", "myresource", "file", test_resource)
    ]
    expected = [
        "Uploading resource directly from file {!r}.".format(str(test_resource)),
        "Revision 7 created of resource 'myresource' for charm 'mycharm'.",
    ]
    assert expected == [rec.message for rec in caplog.records]
    assert test_resource.exists()  # provided by the user, don't touch it


def test_uploadresource_image_call_already_uploaded(caplog, store_mock, config):
    """Upload an oci-image resource, the image itself already being in the registry."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    # fake credentials for the charm/resource, and the final json content
    store_mock.get_oci_registry_credentials.return_value = RegistryCredentials(
        username="testusername",
        password="testpassword",
        image_name="registry.staging.jujucharms.com/charm/charm-id/test-image-name",
    )

    test_json_content = "from charmhub we came, from charmhub we shall return"
    store_mock.get_oci_image_blob.return_value = test_json_content

    # hack into the store mock to save for later the uploaded resource bytes
    uploaded_resource_content = None
    uploaded_resource_filepath = None

    def interceptor(charm_name, resource_name, resource_type, resource_filepath):
        """Intercept the call to save real content (and validate params)."""
        nonlocal uploaded_resource_content, uploaded_resource_filepath

        uploaded_resource_filepath = resource_filepath
        uploaded_resource_content = resource_filepath.read_text()

        assert charm_name == "mycharm"
        assert resource_name == "myresource"
        assert resource_type == "oci-image"
        return Uploaded(ok=True, status=200, revision=7, errors=[])

    store_mock.upload_resource.side_effect = interceptor

    # test
    original_image_digest = "test-digest-given-by-user"
    args = Namespace(
        charm_name="mycharm",
        resource_name="myresource",
        filepath=None,
        image=original_image_digest,
    )
    with patch("charmcraft.commands.store.ImageHandler", autospec=True) as im_class_mock:
        with patch("charmcraft.commands.store.OCIRegistry", autospec=True) as reg_class_mock:
            reg_class_mock.return_value = reg_mock = MagicMock()
            im_class_mock.return_value = im_mock = MagicMock()
            im_mock.check_in_registry.return_value = True
            UploadResourceCommand("group", config).run(args)

    # validate how OCIRegistry was instantiated
    assert reg_class_mock.mock_calls == [
        call(
            config.charmhub.registry_url,
            "charm/charm-id/test-image-name",
            username="testusername",
            password="testpassword",
        )
    ]

    # validate how ImageHandler was used
    assert im_class_mock.mock_calls == [
        call(reg_mock),
        call().check_in_registry(original_image_digest),
    ]

    # check that the uploaded file is fine and that was cleaned
    assert uploaded_resource_content == test_json_content
    assert not uploaded_resource_filepath.exists()  # temporary! shall be cleaned

    assert store_mock.mock_calls == [
        call.get_oci_registry_credentials("mycharm", "myresource"),
        call.get_oci_image_blob("mycharm", "myresource", original_image_digest),
        call.upload_resource("mycharm", "myresource", "oci-image", uploaded_resource_filepath),
    ]

    expected = [
        (
            "Uploading resource from image "
            "charm/charm-id/test-image-name @ test-digest-given-by-user."
        ),
        "Using OCI image from Canonical's registry.",
        "Revision 7 created of resource 'myresource' for charm 'mycharm'.",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_uploadresource_image_call_upload_from_local(caplog, store_mock, config):
    """Upload an oci-image resource, the image is upload from local to Canonical's registry."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    # fake credentials for the charm/resource, the final json content, and the upload result
    store_mock.get_oci_registry_credentials.return_value = RegistryCredentials(
        username="testusername",
        password="testpassword",
        image_name="registry.staging.jujucharms.com/charm/charm-id/test-image-name",
    )

    test_json_content = "from charmhub we came, from charmhub we shall return"
    store_mock.get_oci_image_blob.return_value = test_json_content

    store_mock.upload_resource.return_value = Uploaded(ok=True, status=200, revision=7, errors=[])

    # test
    original_image_digest = "test-digest-given-by-user"
    args = Namespace(
        charm_name="mycharm",
        resource_name="myresource",
        filepath=None,
        image=original_image_digest,
    )
    with patch("charmcraft.commands.store.ImageHandler", autospec=True) as im_class_mock:
        with patch("charmcraft.commands.store.OCIRegistry", autospec=True) as reg_class_mock:
            reg_class_mock.return_value = reg_mock = MagicMock()
            im_class_mock.return_value = im_mock = MagicMock()

            # not in the registry, and then uploaded ok
            im_mock.check_in_registry.return_value = False
            new_image_digest = "new-digest-after-upload"
            im_mock.upload_from_local.return_value = new_image_digest

            UploadResourceCommand("group", config).run(args)

    # validate how ImageHandler was used
    assert im_class_mock.mock_calls == [
        call(reg_mock),
        call().check_in_registry(original_image_digest),
        call().upload_from_local(original_image_digest),
    ]

    assert store_mock.mock_calls == [
        call.get_oci_registry_credentials("mycharm", "myresource"),
        call.get_oci_image_blob("mycharm", "myresource", new_image_digest),
        call.upload_resource("mycharm", "myresource", "oci-image", ANY),
    ]

    expected = [
        (
            "Uploading resource from image "
            "charm/charm-id/test-image-name @ test-digest-given-by-user."
        ),
        "Remote image not found, uploading from local registry.",
        "Image uploaded, new remote digest: new-digest-after-upload.",
        "Revision 7 created of resource 'myresource' for charm 'mycharm'.",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_uploadresource_image_call_missing_everywhere(caplog, store_mock, config):
    """Upload an oci-image resource, but the image is not found remote nor locally."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    # fake credentials for the charm/resource, the final json content, and the upload result
    store_mock.get_oci_registry_credentials.return_value = RegistryCredentials(
        username="testusername",
        password="testpassword",
        image_name="registry.staging.jujucharms.com/charm/charm-id/test-image-name",
    )

    # test
    original_image_digest = "test-digest-given-by-user"
    args = Namespace(
        charm_name="mycharm",
        resource_name="myresource",
        filepath=None,
        image=original_image_digest,
    )
    with patch("charmcraft.commands.store.ImageHandler", autospec=True) as im_class_mock:
        with patch("charmcraft.commands.store.OCIRegistry", autospec=True) as reg_class_mock:
            reg_class_mock.return_value = reg_mock = MagicMock()
            im_class_mock.return_value = im_mock = MagicMock()

            # not in the remote registry, not locally either
            im_mock.check_in_registry.return_value = False
            im_mock.upload_from_local.return_value = None

            UploadResourceCommand("group", config).run(args)

    # validate how ImageHandler was used
    assert im_class_mock.mock_calls == [
        call(reg_mock),
        call().check_in_registry(original_image_digest),
        call().upload_from_local(original_image_digest),
    ]

    assert store_mock.mock_calls == [
        call.get_oci_registry_credentials("mycharm", "myresource"),
    ]

    expected = [
        (
            "Uploading resource from "
            "image charm/charm-id/test-image-name @ test-digest-given-by-user."
        ),
        "Remote image not found, uploading from local registry.",
        (
            "Image with digest test-digest-given-by-user is not available in "
            "the Canonical's registry nor locally."
        ),
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_uploadresource_call_error(caplog, store_mock, config, tmp_path):
    """Simple upload but with a response indicating an error."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    errors = [
        Error(message="text 1", code="missing-stuff"),
        Error(message="other long error text", code="broken"),
    ]
    store_response = Uploaded(ok=False, status=400, revision=None, errors=errors)
    store_mock.upload_resource.return_value = store_response

    test_resource = tmp_path / "mystuff.bin"
    test_resource.write_text("sample stuff")
    args = Namespace(charm_name="mycharm", resource_name="myresource", filepath=test_resource)
    UploadResourceCommand("group", config).run(args)

    expected = [
        "Upload failed with status 400:",
        "- missing-stuff: text 1",
        "- broken: other long error text",
    ]
    assert expected == [rec.message for rec in caplog.records]


# -- tests for list resource revisions command


def test_resourcerevisions_simple(caplog, store_mock, config):
    """Happy path of one result from the Store."""

    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = [
        ResourceRevision(revision=1, size=50, created_at=datetime.datetime(2020, 7, 3, 2, 30, 40)),
    ]
    store_mock.list_resource_revisions.return_value = store_response

    args = Namespace(charm_name="testcharm", resource_name="testresource")
    ListResourceRevisionsCommand("group", config).run(args)

    assert store_mock.mock_calls == [
        call.list_resource_revisions("testcharm", "testresource"),
    ]
    expected = [
        "Revision    Created at    Size",
        "1           2020-07-03     50B",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_resourcerevisions_empty(caplog, store_mock, config):
    """No results from the store."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    store_response = []
    store_mock.list_resource_revisions.return_value = store_response

    args = Namespace(charm_name="testcharm", resource_name="testresource")
    ListResourceRevisionsCommand("group", config).run(args)

    expected = [
        "No revisions found.",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_resourcerevisions_ordered_by_revision(caplog, store_mock, config):
    """Results are presented ordered by revision in the table."""
    caplog.set_level(logging.INFO, logger="charmcraft.commands")

    # three Revisions with all values weirdly similar, the only difference is revision, so
    # we really assert later that it was used for ordering
    tstamp = datetime.datetime(2020, 7, 3, 20, 30, 40)
    store_response = [
        ResourceRevision(revision=1, size=5000, created_at=tstamp),
        ResourceRevision(revision=3, size=34450520, created_at=tstamp),
        ResourceRevision(revision=4, size=876543, created_at=tstamp),
        ResourceRevision(revision=2, size=50, created_at=tstamp),
    ]
    store_mock.list_resource_revisions.return_value = store_response

    args = Namespace(charm_name="testcharm", resource_name="testresource")
    ListResourceRevisionsCommand("group", config).run(args)

    expected = [
        "Revision    Created at    Size",
        "4           2020-07-03  856.0K",
        "3           2020-07-03   32.9M",
        "2           2020-07-03     50B",
        "1           2020-07-03    4.9K",
    ]
    assert expected == [rec.message for rec in caplog.records]
