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

"""Tests for the Store API layer (code in store/store.py)."""

import logging
from unittest.mock import patch, call, MagicMock

import pytest
from dateutil import parser

from charmcraft.utils import ResourceOption
from charmcraft.commands.store.store import Store, Library


@pytest.fixture
def client_mock():
    """Fixture to provide a mocked client."""
    client_mock = MagicMock()
    with patch("charmcraft.commands.store.store.Client", lambda api, storage: client_mock):
        yield client_mock


# -- tests for client usage


def test_client_init(config):
    """Check that the client is initiated ok even without config."""
    with patch("charmcraft.commands.store.store.Client") as client_mock:
        Store(config.charmhub)
    assert client_mock.mock_calls == [
        call(config.charmhub.api_url, config.charmhub.storage_url),
    ]


# -- tests for auth


def test_login(client_mock, config):
    """Simple login case."""
    store = Store(config.charmhub)
    result = store.login()
    assert client_mock.mock_calls == [
        call.clear_credentials(),
        call.get("/v1/whoami"),
    ]
    assert result is None


def test_logout(client_mock, config):
    """Simple logout case."""
    store = Store(config.charmhub)
    result = store.logout()
    assert client_mock.mock_calls == [
        call.clear_credentials(),
    ]
    assert result is None


def test_whoami(client_mock, config):
    """Simple whoami case."""
    store = Store(config.charmhub)
    auth_response = {"display-name": "John Doe", "username": "jdoe", "id": "-1"}
    client_mock.get.return_value = auth_response

    result = store.whoami()

    assert client_mock.mock_calls == [
        call.get("/v1/whoami"),
    ]
    assert result.name == "John Doe"
    assert result.username == "jdoe"
    assert result.userid == "-1"


# -- tests for register and list names


def test_register_name(client_mock, config):
    """Simple register case."""
    store = Store(config.charmhub)
    result = store.register_name("testname", "stuff")

    assert client_mock.mock_calls == [
        call.post("/v1/charm", {"name": "testname", "type": "stuff"}),
    ]
    assert result is None


def test_list_registered_names_empty(client_mock, config):
    """List registered names getting an empty response."""
    store = Store(config.charmhub)

    auth_response = {"results": []}
    client_mock.get.return_value = auth_response

    result = store.list_registered_names()

    assert client_mock.mock_calls == [call.get("/v1/charm")]
    assert result == []


def test_list_registered_names_multiple(client_mock, config):
    """List registered names getting a multiple response."""
    store = Store(config.charmhub)

    auth_response = {
        "results": [
            {"name": "name1", "type": "charm", "private": False, "status": "status1"},
            {"name": "name2", "type": "bundle", "private": True, "status": "status2"},
        ]
    }
    client_mock.get.return_value = auth_response

    result = store.list_registered_names()

    assert client_mock.mock_calls == [call.get("/v1/charm")]
    item1, item2 = result
    assert item1.name == "name1"
    assert item1.entity_type == "charm"
    assert not item1.private
    assert item1.status == "status1"
    assert item2.name == "name2"
    assert item2.entity_type == "bundle"
    assert item2.private
    assert item2.status == "status2"


# -- tests for the upload functionality (both for charm/bundles and resources)


def test_upload_straightforward(client_mock, caplog, config):
    """The full and successful upload case."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    store = Store(config.charmhub)

    # the first response, for when pushing bytes
    test_upload_id = "test-upload-id"
    client_mock.push.return_value = test_upload_id

    # the second response, for telling the store it was pushed
    test_status_url = "https://store.c.c/status"
    client_mock.post.return_value = {"status-url": test_status_url}

    # the third response, status ok (note the patched UPLOAD_ENDING_STATUSES below)
    test_revision = 123
    test_status_ok = "test-status"
    status_response = {
        "revisions": [{"status": test_status_ok, "revision": test_revision, "errors": None}]
    }
    client_mock.get.return_value = status_response

    test_status_resolution = "test-ok-or-not"
    fake_statuses = {test_status_ok: test_status_resolution}
    test_filepath = "test-filepath"
    test_endpoint = "/v1/test/revisions/endpoint/"
    with patch.dict("charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES", fake_statuses):
        result = store._upload(test_endpoint, test_filepath)

    # check all client calls
    assert client_mock.mock_calls == [
        call.push(test_filepath),
        call.post(test_endpoint, {"upload-id": test_upload_id}),
        call.get(test_status_url),
    ]

    # check result (build after patched ending struct)
    assert result.ok == test_status_resolution
    assert result.status == test_status_ok
    assert result.revision == test_revision

    # check logs
    expected = [
        "Upload test-upload-id started, got status url https://store.c.c/status",
        "Status checked: " + str(status_response),
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_polls_status(client_mock, caplog, config):
    """Upload polls status url until the end is indicated."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    store = Store(config.charmhub)

    # first and second response, for pushing bytes and let the store know about it
    test_upload_id = "test-upload-id"
    client_mock.push.return_value = test_upload_id
    test_status_url = "https://store.c.c/status"
    client_mock.post.return_value = {"status-url": test_status_url}

    # the status checking response, will answer something not done yet twice, then ok
    test_revision = 123
    test_status_ok = "test-status"
    status_response_1 = {
        "revisions": [{"status": "still-scanning", "revision": None, "errors": None}]
    }
    status_response_2 = {
        "revisions": [{"status": "more-revisions", "revision": None, "errors": None}]
    }
    status_response_3 = {
        "revisions": [{"status": test_status_ok, "revision": test_revision, "errors": None}]
    }
    client_mock.get.side_effect = [
        status_response_1,
        status_response_2,
        status_response_3,
    ]

    test_status_resolution = "clean and crispy"
    fake_statuses = {test_status_ok: test_status_resolution}
    with patch.dict("charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES", fake_statuses):
        with patch("charmcraft.commands.store.store.POLL_DELAY", 0.01):
            result = store._upload("/test/endpoint/", "some-filepath")

    # check the status-checking client calls (kept going until third one)
    assert client_mock.mock_calls[2:] == [
        call.get(test_status_url),
        call.get(test_status_url),
        call.get(test_status_url),
    ]

    # check result which must have values from final result
    assert result.ok == test_status_resolution
    assert result.status == test_status_ok
    assert result.revision == test_revision

    # check logs
    expected = [
        "Upload test-upload-id started, got status url https://store.c.c/status",
        "Status checked: " + str(status_response_1),
        "Status checked: " + str(status_response_2),
        "Status checked: " + str(status_response_3),
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_error(client_mock, config):
    """The upload ended in error."""
    store = Store(config.charmhub)

    # the first response, for when pushing bytes
    test_upload_id = "test-upload-id"
    client_mock.push.return_value = test_upload_id

    # the second response, for telling the store it was pushed
    test_status_url = "https://store.c.c/status"
    client_mock.post.return_value = {"status-url": test_status_url}

    # the third response, status in error (note the patched UPLOAD_ENDING_STATUSES below)
    test_revision = 123
    test_status_bad = "test-status"
    status_response = {
        "revisions": [
            {
                "status": test_status_bad,
                "revision": test_revision,
                "errors": [
                    {"message": "error text 1", "code": "error-code-1"},
                    {"message": "error text 2", "code": "error-code-2"},
                ],
            }
        ]
    }
    client_mock.get.return_value = status_response

    test_status_resolution = "test-ok-or-not"
    fake_statuses = {test_status_bad: test_status_resolution}
    test_filepath = "test-filepath"
    with patch.dict("charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES", fake_statuses):
        result = store._upload("/test/endpoint/", test_filepath)

    # check result
    assert result.ok == test_status_resolution
    assert result.status == test_status_bad
    assert result.revision == test_revision
    error1, error2 = result.errors
    assert error1.message == "error text 1"
    assert error1.code == "error-code-1"
    assert error2.message == "error text 2"
    assert error2.code == "error-code-2"


def test_upload_charmbundles_endpoint(config):
    """The bundle/charm upload prepares ok the endpoint and calls the generic _upload."""
    store = Store(config.charmhub)
    test_results = "test-results"

    with patch.object(store, "_upload") as mock:
        mock.return_value = test_results
        result = store.upload("test-charm", "test-filepath")
    mock.assert_called_once_with("/v1/charm/test-charm/revisions", "test-filepath")
    assert result == test_results


def test_upload_resources_endpoint(config):
    """The resource upload prepares ok the endpoint and calls the generic _upload."""
    store = Store(config.charmhub)
    test_results = "test-results"

    with patch.object(store, "_upload") as mock:
        mock.return_value = test_results
        result = store.upload_resource("test-charm", "test-resource", "test-type", "test-filepath")
    expected_endpoint = "/v1/charm/test-charm/resources/test-resource/revisions"
    mock.assert_called_once_with(
        expected_endpoint, "test-filepath", extra_fields={"type": "test-type"}
    )
    assert result == test_results


def test_upload_including_extra_parameters(client_mock, caplog, config):
    """Verify that the upload includes extra parameters if given."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    store = Store(config.charmhub)

    # the first response, for when pushing bytes
    test_upload_id = "test-upload-id"
    client_mock.push.return_value = test_upload_id

    # the second response, for telling the store it was pushed
    test_status_url = "https://store.c.c/status"
    client_mock.post.return_value = {"status-url": test_status_url}

    # the third response, status ok (note the patched UPLOAD_ENDING_STATUSES below)
    test_revision = 123
    test_status_ok = "test-status"
    status_response = {
        "revisions": [{"status": test_status_ok, "revision": test_revision, "errors": None}]
    }
    client_mock.get.return_value = status_response

    test_status_resolution = "test-ok-or-not"
    fake_statuses = {test_status_ok: test_status_resolution}
    test_filepath = "test-filepath"
    test_endpoint = "/v1/test/revisions/endpoint/"
    extra_fields = {"extra-key": "1", "more": "2"}
    with patch.dict("charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES", fake_statuses):
        store._upload(test_endpoint, test_filepath, extra_fields=extra_fields)

    # check all client calls
    assert client_mock.mock_calls == [
        call.push(test_filepath),
        call.post(test_endpoint, {"upload-id": test_upload_id, "extra-key": "1", "more": "2"}),
        call.get(test_status_url),
    ]


# -- tests for list revisions


def test_list_revisions_ok(client_mock, config):
    """One revision ok."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "revisions": [
            {
                "revision": 7,
                "version": "v7",
                "created-at": "2020-06-29T22:11:00.123",
                "status": "approved",
                "errors": None,
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            }
        ]
    }

    result = store.list_revisions("some-name")

    assert client_mock.mock_calls == [call.get("/v1/charm/some-name/revisions")]

    (item,) = result
    assert item.revision == 7
    assert item.version == "v7"
    assert item.created_at == parser.parse("2020-06-29T22:11:00.123")
    assert item.status == "approved"
    assert item.errors == []


def test_list_revisions_empty(client_mock, config):
    """No revisions listed."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {"revisions": []}

    result = store.list_revisions("some-name")

    assert client_mock.mock_calls == [call.get("/v1/charm/some-name/revisions")]
    assert result == []


def test_list_revisions_errors(client_mock, config):
    """One revision with errors."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "revisions": [
            {
                "revision": 7,
                "version": "v7",
                "created-at": "2020-06-29T22:11:00.123",
                "status": "rejected",
                "errors": [
                    {"message": "error text 1", "code": "error-code-1"},
                    {"message": "error text 2", "code": "error-code-2"},
                ],
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            }
        ]
    }

    result = store.list_revisions("some-name")

    assert client_mock.mock_calls == [call.get("/v1/charm/some-name/revisions")]

    (item,) = result
    error1, error2 = item.errors
    assert error1.message == "error text 1"
    assert error1.code == "error-code-1"
    assert error2.message == "error text 2"
    assert error2.code == "error-code-2"


def test_list_revisions_several_mixed(client_mock, config):
    """All cases mixed."""
    client_mock.get.return_value = {
        "revisions": [
            {
                "revision": 1,
                "version": "v1",
                "created-at": "2020-06-29T22:11:01",
                "status": "rejected",
                "errors": [
                    {"message": "error", "code": "code"},
                ],
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            },
            {
                "revision": 2,
                "version": "v2",
                "created-at": "2020-06-29T22:11:02",
                "status": "approved",
                "errors": None,
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            },
        ]
    }

    store = Store(config.charmhub)
    result = store.list_revisions("some-name")

    (item1, item2) = result

    assert item1.revision == 1
    assert item1.version == "v1"
    assert item1.created_at == parser.parse("2020-06-29T22:11:01")
    assert item1.status == "rejected"
    (error,) = item1.errors
    assert error.message == "error"
    assert error.code == "code"

    assert item2.revision == 2
    assert item2.version == "v2"
    assert item2.created_at == parser.parse("2020-06-29T22:11:02")
    assert item2.status == "approved"
    assert item2.errors == []


# -- tests for release


def test_release_simple(client_mock, config):
    """Releasing a revision into one channel."""
    store = Store(config.charmhub)
    store.release("testname", 123, ["somechannel"], [])

    expected_body = [{"revision": 123, "channel": "somechannel", "resources": []}]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/testname/releases", expected_body),
    ]


def test_release_multiple_channels(client_mock, config):
    """Releasing a revision into multiple channels."""
    store = Store(config.charmhub)
    store.release("testname", 123, ["channel1", "channel2", "channel3"], [])

    expected_body = [
        {"revision": 123, "channel": "channel1", "resources": []},
        {"revision": 123, "channel": "channel2", "resources": []},
        {"revision": 123, "channel": "channel3", "resources": []},
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/testname/releases", expected_body),
    ]


def test_release_with_resources(client_mock, config):
    """Releasing with resources attached."""
    store = Store(config.charmhub)
    r1 = ResourceOption(name="foo", revision=3)
    r2 = ResourceOption(name="bar", revision=17)
    store.release("testname", 123, ["channel1", "channel2"], [r1, r2])

    expected_body = [
        {
            "revision": 123,
            "channel": "channel1",
            "resources": [
                {"name": "foo", "revision": 3},
                {"name": "bar", "revision": 17},
            ],
        },
        {
            "revision": 123,
            "channel": "channel2",
            "resources": [
                {"name": "foo", "revision": 3},
                {"name": "bar", "revision": 17},
            ],
        },
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/testname/releases", expected_body),
    ]


# -- tests for status


def test_status_ok(client_mock, config):
    """Get all the release information."""
    client_mock.get.return_value = {
        "channel-map": [
            {
                "channel": "latest/beta",
                "expiration-date": None,
                "progressive": {"paused": None, "percentage": None},
                "revision": 5,
                "when": "2020-07-16T18:45:24Z",
                "resources": [],
                "base": {"architecture": "amd64", "channel": "20.04", "name": "ubuntu"},
            },
            {
                "channel": "latest/edge/mybranch",
                "expiration-date": "2020-08-16T18:46:02Z",
                "progressive": {"paused": None, "percentage": None},
                "revision": 10,
                "when": "2020-07-16T18:46:02Z",
                "resources": [],
                "base": {"architecture": "amd64", "channel": "20.04", "name": "ubuntu"},
            },
        ],
        "package": {
            "channels": [
                {
                    "branch": None,
                    "fallback": None,
                    "name": "latest/stable",
                    "risk": "stable",
                    "track": "latest",
                },
                {
                    "branch": "mybranch",
                    "fallback": "latest/stable",
                    "name": "latest/edge/mybranch",
                    "risk": "edge",
                    "track": "latest",
                },
            ]
        },
        "revisions": [
            {
                "revision": 5,
                "version": "5",
                "created-at": "2020-06-29T22:11:05",
                "status": "approved",
                "errors": None,
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            },
            {
                "revision": 10,
                "version": "63a852b",
                "created-at": "2020-06-29T22:11:10",
                "status": "approved",
                "errors": None,
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            },
        ],
    }

    store = Store(config.charmhub)
    channel_map, channels, revisions = store.list_releases("testname")

    # check how the client is used
    assert client_mock.mock_calls == [
        call.get("/v1/charm/testname/releases"),
    ]

    # check response
    cmap1, cmap2 = channel_map
    assert cmap1.revision == 5
    assert cmap1.channel == "latest/beta"
    assert cmap1.expires_at is None
    assert cmap1.resources == []
    assert cmap1.base.name == "ubuntu"
    assert cmap1.base.channel == "20.04"
    assert cmap1.base.architecture == "amd64"
    assert cmap2.revision == 10
    assert cmap2.channel == "latest/edge/mybranch"
    assert cmap2.expires_at == parser.parse("2020-08-16T18:46:02Z")
    assert cmap2.resources == []
    assert cmap2.base.name == "ubuntu"
    assert cmap2.base.channel == "20.04"
    assert cmap2.base.architecture == "amd64"

    channel1, channel2 = channels
    assert channel1.name == "latest/stable"
    assert channel1.track == "latest"
    assert channel1.risk == "stable"
    assert channel1.branch is None
    assert channel2.name == "latest/edge/mybranch"
    assert channel2.track == "latest"
    assert channel2.risk == "edge"
    assert channel2.branch == "mybranch"

    rev1, rev2 = revisions
    assert rev1.revision == 5
    assert rev1.version == "5"
    assert rev1.created_at == parser.parse("2020-06-29T22:11:05")
    assert rev1.status == "approved"
    assert rev1.errors == []
    (base,) = rev1.bases
    assert base.name == "ubuntu"
    assert base.channel == "20.04"
    assert base.architecture == "amd64"
    assert rev2.revision == 10
    assert rev2.version == "63a852b"
    assert rev2.created_at == parser.parse("2020-06-29T22:11:10")
    assert rev2.status == "approved"
    assert rev2.errors == []
    (base,) = rev2.bases
    assert base.name == "ubuntu"
    assert base.channel == "20.04"
    assert base.architecture == "amd64"


def test_status_with_resources(client_mock, config):
    """Get all the release information."""
    client_mock.get.return_value = {
        "channel-map": [
            {
                "channel": "latest/stable",
                "expiration-date": None,
                "progressive": {"paused": None, "percentage": None},
                "revision": 5,
                "when": "2020-07-16T18:45:24Z",
                "resources": [
                    {
                        "name": "test-resource-1",
                        "revision": 2,
                        "type": "file",
                    },
                ],
                "base": {"architecture": "amd64", "channel": "20.04", "name": "ubuntu"},
            },
            {
                "channel": "latest/edge",
                "expiration-date": "2020-08-16T18:46:02Z",
                "progressive": {"paused": None, "percentage": None},
                "revision": 5,
                "when": "2020-07-16T18:46:02Z",
                "resources": [
                    {
                        "name": "test-resource-1",
                        "revision": 2,
                        "type": "file",
                    },
                    {
                        "name": "test-resource-2",
                        "revision": 329,
                        "type": "file",
                    },
                ],
                "base": {"architecture": "amd64", "channel": "20.04", "name": "ubuntu"},
            },
        ],
        "package": {
            "channels": [
                {
                    "branch": None,
                    "fallback": None,
                    "name": "latest/edge",
                    "risk": "edge",
                    "track": "latest",
                },
                {
                    "branch": None,
                    "fallback": None,
                    "name": "latest/stable",
                    "risk": "stable",
                    "track": "latest",
                },
            ]
        },
        "revisions": [
            {
                "revision": 5,
                "version": "5",
                "created-at": "2020-06-29T22:11:05",
                "status": "approved",
                "errors": None,
                "bases": [{"architecture": "amd64", "channel": "20.04", "name": "ubuntu"}],
            },
        ],
    }

    store = Store(config.charmhub)
    channel_map, _, _ = store.list_releases("testname")

    # check response
    cmap1, cmap2 = channel_map

    assert cmap1.revision == 5
    assert cmap1.channel == "latest/stable"
    assert cmap1.expires_at is None
    (res,) = cmap1.resources
    assert res.name == "test-resource-1"
    assert res.revision == 2
    assert res.resource_type == "file"

    assert cmap2.revision == 5
    assert cmap2.channel == "latest/edge"
    assert cmap2.expires_at == parser.parse("2020-08-16T18:46:02Z")
    (res1, res2) = cmap2.resources
    assert res1.name == "test-resource-1"
    assert res1.revision == 2
    assert res1.resource_type == "file"
    assert res2.name == "test-resource-2"
    assert res2.revision == 329
    assert res2.resource_type == "file"


# -- tests for library related functions


def test_create_library_id(client_mock, config):
    """Create a new library in the store."""
    store = Store(config.charmhub)
    client_mock.post.return_value = {"library-id": "test-lib-id"}

    result = store.create_library_id("test-charm-name", "test-lib-name")

    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/test-charm-name", {"library-name": "test-lib-name"}),
    ]
    assert result == "test-lib-id"


def test_create_library_revision(client_mock, config):
    """Create a new library revision in the store."""
    test_charm_name = "test-charm-name"
    test_lib_name = "test-lib-name"
    test_lib_id = "test-lib-id"
    test_api = "test-api-version"
    test_patch = "test-patch-version"
    test_content = "test content with quite a lot of funny Python code :p"
    test_hash = "1234"

    store = Store(config.charmhub)
    client_mock.post.return_value = {
        "api": test_api,
        "content": test_content,
        "hash": test_hash,
        "library-id": test_lib_id,
        "library-name": test_lib_name,
        "charm-name": test_charm_name,
        "patch": test_patch,
    }

    result_lib = store.create_library_revision(
        test_charm_name, test_lib_id, test_api, test_patch, test_content, test_hash
    )

    payload = {
        "api": test_api,
        "patch": test_patch,
        "content": test_content,
        "hash": test_hash,
    }
    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/test-charm-name/" + test_lib_id, payload),
    ]
    assert result_lib.api == test_api
    assert result_lib.content == test_content
    assert result_lib.content_hash == test_hash
    assert result_lib.lib_id == test_lib_id
    assert result_lib.lib_name == test_lib_name
    assert result_lib.charm_name == test_charm_name
    assert result_lib.patch == test_patch


def test_get_library(client_mock, config):
    """Get all the information (including content) for a library revision."""
    test_charm_name = "test-charm-name"
    test_lib_name = "test-lib-name"
    test_lib_id = "test-lib-id"
    test_api = "test-api-version"
    test_patch = "test-patch-version"
    test_content = "test content with quite a lot of funny Python code :p"
    test_hash = "1234"

    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "api": test_api,
        "content": test_content,
        "hash": test_hash,
        "library-id": test_lib_id,
        "library-name": test_lib_name,
        "charm-name": test_charm_name,
        "patch": test_patch,
    }

    result_lib = store.get_library(test_charm_name, test_lib_id, test_api)

    assert client_mock.mock_calls == [
        call.get("/v1/charm/libraries/test-charm-name/{}?api={}".format(test_lib_id, test_api)),
    ]
    assert result_lib.api == test_api
    assert result_lib.content == test_content
    assert result_lib.content_hash == test_hash
    assert result_lib.lib_id == test_lib_id
    assert result_lib.lib_name == test_lib_name
    assert result_lib.charm_name == test_charm_name
    assert result_lib.patch == test_patch


def test_get_tips_simple(client_mock, config):
    """Get info for a lib, simple case with successful result."""
    test_charm_name = "test-charm-name"
    test_lib_name = "test-lib-name"
    test_lib_id = "test-lib-id"
    test_api = "test-api-version"
    test_patch = "test-patch-version"
    test_content = "test content with quite a lot of funny Python code :p"
    test_hash = "1234"

    store = Store(config.charmhub)
    client_mock.post.return_value = {
        "libraries": [
            {
                "api": test_api,
                "content": test_content,
                "hash": test_hash,
                "library-id": test_lib_id,
                "library-name": test_lib_name,
                "charm-name": test_charm_name,
                "patch": test_patch,
            }
        ]
    }

    query_info = [
        {"lib_id": test_lib_id},
    ]
    result = store.get_libraries_tips(query_info)

    payload = [
        {"library-id": test_lib_id},
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/bulk", payload),
    ]
    expected = {
        (test_lib_id, test_api): Library(
            api=test_api,
            content=test_content,
            content_hash=test_hash,
            lib_id=test_lib_id,
            lib_name=test_lib_name,
            charm_name=test_charm_name,
            patch=test_patch,
        ),
    }
    assert result == expected


def test_get_tips_empty(client_mock, config):
    """Get info for a lib, with an empty response."""
    test_lib_id = "test-lib-id"

    store = Store(config.charmhub)
    client_mock.post.return_value = {"libraries": []}

    query_info = [
        {"lib_id": test_lib_id},
    ]
    result = store.get_libraries_tips(query_info)

    payload = [
        {"library-id": test_lib_id},
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/bulk", payload),
    ]
    assert result == {}


def test_get_tips_several(client_mock, config):
    """Get info for multiple libs at once."""
    test_charm_name_1 = "test-charm-name-1"
    test_lib_name_1 = "test-lib-name-1"
    test_lib_id_1 = "test-lib-id-1"
    test_api_1 = "test-api-version-1"
    test_patch_1 = "test-patch-version-1"
    test_content_1 = "test content with quite a lot of funny Python code :p"
    test_hash_1 = "1234"

    test_charm_name_2 = "test-charm-name-2"
    test_lib_name_2 = "test-lib-name-2"
    test_lib_id_2 = "test-lib-id-2"
    test_api_2 = "test-api-version-2"
    test_patch_2 = "test-patch-version-2"
    test_content_2 = "more awesome Python code :)"
    test_hash_2 = "5678"

    store = Store(config.charmhub)
    client_mock.post.return_value = {
        "libraries": [
            {
                "api": test_api_1,
                "content": test_content_1,
                "hash": test_hash_1,
                "library-id": test_lib_id_1,
                "library-name": test_lib_name_1,
                "charm-name": test_charm_name_1,
                "patch": test_patch_1,
            },
            {
                "api": test_api_2,
                "content": test_content_2,
                "hash": test_hash_2,
                "library-id": test_lib_id_2,
                "library-name": test_lib_name_2,
                "charm-name": test_charm_name_2,
                "patch": test_patch_2,
            },
        ]
    }

    query_info = [
        {"lib_id": test_lib_id_1},
        {"lib_id": test_lib_id_2},
    ]
    result = store.get_libraries_tips(query_info)

    payload = [
        {"library-id": test_lib_id_1},
        {"library-id": test_lib_id_2},
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/bulk", payload),
    ]
    expected = {
        (test_lib_id_1, test_api_1): Library(
            api=test_api_1,
            content=test_content_1,
            content_hash=test_hash_1,
            lib_id=test_lib_id_1,
            lib_name=test_lib_name_1,
            charm_name=test_charm_name_1,
            patch=test_patch_1,
        ),
        (test_lib_id_2, test_api_2): Library(
            api=test_api_2,
            content=test_content_2,
            content_hash=test_hash_2,
            lib_id=test_lib_id_2,
            lib_name=test_lib_name_2,
            charm_name=test_charm_name_2,
            patch=test_patch_2,
        ),
    }
    assert result == expected


def test_get_tips_query_combinations(client_mock, config):
    """Use all the combinations to specify what's queried."""
    store = Store(config.charmhub)
    client_mock.post.return_value = {"libraries": []}

    query_info = [
        {"lib_id": "test-lib-id-1"},
        {"lib_id": "test-lib-id-2", "api": 2},
        {"charm_name": "test-charm-name-3"},
        {"charm_name": "test-charm-name-4", "api": 4},
        {"charm_name": "test-charm-name-5", "lib_name": "test-lib-name-5"},
        {"charm_name": "test-charm-name-6", "lib_name": "test-lib-name-6", "api": 6},
    ]
    store.get_libraries_tips(query_info)

    payload = [
        {"library-id": "test-lib-id-1"},
        {"library-id": "test-lib-id-2", "api": 2},
        {"charm-name": "test-charm-name-3"},
        {"charm-name": "test-charm-name-4", "api": 4},
        {"charm-name": "test-charm-name-5", "library-name": "test-lib-name-5"},
        {
            "charm-name": "test-charm-name-6",
            "library-name": "test-lib-name-6",
            "api": 6,
        },
    ]
    assert client_mock.mock_calls == [
        call.post("/v1/charm/libraries/bulk", payload),
    ]


# -- tests for list resources


def test_list_resources_ok(client_mock, config):
    """One resource ok."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "resources": [
            {
                "name": "testresource",
                "optional": True,
                "revision": 9,
                "type": "file",
            },
        ]
    }

    result = store.list_resources("some-name")

    assert client_mock.mock_calls == [call.get("/v1/charm/some-name/resources")]

    (item,) = result
    assert item.name == "testresource"
    assert item.optional
    assert item.revision == 9
    assert item.resource_type == "file"


def test_list_resources_empty(client_mock, config):
    """No resources listed."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {"resources": []}

    result = store.list_resources("some-name")

    assert client_mock.mock_calls == [call.get("/v1/charm/some-name/resources")]
    assert result == []


def test_list_resources_several(client_mock, config):
    """Several items returned."""
    client_mock.get.return_value = {
        "resources": [
            {
                "name": "testresource1",
                "optional": True,
                "revision": 123,
                "type": "file",
            },
            {
                "name": "testresource2",
                "optional": False,
                "revision": 678,
                "type": "file",
            },
        ]
    }

    store = Store(config.charmhub)
    result = store.list_resources("some-name")

    (item1, item2) = result

    assert item1.name == "testresource1"
    assert item1.optional is True
    assert item1.revision == 123
    assert item1.resource_type == "file"

    assert item2.name == "testresource2"
    assert item2.optional is False
    assert item2.revision == 678
    assert item2.resource_type == "file"


# -- tests for list resource revisions


def test_list_resource_revisions_ok(client_mock, config):
    """One resource revision ok."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "revisions": [
            {
                "created-at": "2021-02-11T13:43:22.396606",
                "name": "otherstuff",
                "revision": 1,
                "sha256": "1bf0399c2de1240777ba73785f1ff1de5331f12853765a0",
                "sha3-384": "deb9369cb2b9e86ad44160e93da43d240e6388c5dc67b8e2a5a3c2a36a26fe4c89",
                "sha384": "eaaba6aa119da415e6ad778358a8530c47fefbe3ceced258e8c25530107dc7908e",
                "sha512": (
                    "b8cfe885d49285d8546885167a72fd56ea23480e17c9cdd8e06b45239d79b774c6d6fc09d"
                ),
                "size": 500,
            },
        ]
    }

    result = store.list_resource_revisions("charm-name", "resource-name")

    assert client_mock.mock_calls == [
        call.get("/v1/charm/charm-name/resources/resource-name/revisions")
    ]

    (item,) = result
    assert item.revision == 1
    assert item.created_at == parser.parse("2021-02-11T13:43:22.396606")
    assert item.size == 500


def test_list_resource_revisions_empty(client_mock, config):
    """No resource revisions listed."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {"revisions": []}

    result = store.list_resource_revisions("charm-name", "resource-name")

    assert client_mock.mock_calls == [
        call.get("/v1/charm/charm-name/resources/resource-name/revisions")
    ]
    assert result == []


def test_list_resource_revisions_several(client_mock, config):
    """Several items returned."""
    client_mock.get.return_value = {
        "revisions": [
            {
                "created-at": "2021-02-11T13:43:22.396606",
                "name": "otherstuff",
                "revision": 1,
                "sha256": "1bf0399c2de1240777ba73785f1ff1de5331f12853765a0",
                "sha3-384": "deb9369cb2b9e86ad44160e93da43d240e6388c5dc67b8e2a5a3c2a36a26fe4c89",
                "sha384": "eaaba6aa119da415e6ad778358a8530c47fefbe3ceced258e8c25530107dc7908e",
                "sha512": (
                    "b8cfe885d49285d8546885167a72fd56ea23480e17c9cdd8e06b45239d79b774c6d6fc09d"
                ),
                "size": 500,
            },
            {
                "created-at": "2021-02-11T14:23:55.659148",
                "name": "otherstuff",
                "revision": 2,
                "sha256": "73785f1ff1de5331f12853765a01bf0399c2de1240777ba",
                "sha3-384": "60e93da43d240e6388c5dc67b8e2a5a3c2a36a26fe4c89deb9369cb2b5e86ad441",
                "sha384": "778358a8530c47fefbe3ceced258e8c25530107dc7908eeaaba6aa119dad15e6ad",
                "sha512": (
                    "05167a72fd56ea23480e17c9cdd8e06b45239d79b774c6d6fc09db8cfe885d49285d8547c"
                ),
                "size": 420,
            },
        ]
    }

    store = Store(config.charmhub)
    result = store.list_resource_revisions("charm-name", "resource-name")

    (item1, item2) = result

    assert item1.revision == 1
    assert item1.created_at == parser.parse("2021-02-11T13:43:22.396606")
    assert item1.size == 500

    assert item2.revision == 2
    assert item2.created_at == parser.parse("2021-02-11T14:23:55.659148")
    assert item2.size == 420


# -- tests for OCI related functions


def test_get_oci_registry_credentials(client_mock, config):
    """Get the credentials to hit the OCI Registry."""
    store = Store(config.charmhub)
    client_mock.get.return_value = {
        "image-name": "test-image-name",
        "username": "jane-doe",
        "password": "oh boy this is so secret!",
    }
    result = store.get_oci_registry_credentials("charm-name", "resource-name")

    assert client_mock.mock_calls == [
        call.get("/v1/charm/charm-name/resources/resource-name/oci-image/upload-credentials")
    ]
    assert result.image_name == "test-image-name"
    assert result.username == "jane-doe"
    assert result.password == "oh boy this is so secret!"


def test_get_oci_image_blob(client_mock, config):
    """Get the blob generated by Charmhub to refer to the OCI image."""
    store = Store(config.charmhub)
    client_mock.post.return_value = "some opaque stuff"
    result = store.get_oci_image_blob("charm-name", "resource-name", "a-very-specific-digest")

    assert client_mock.mock_calls == [
        call.post(
            "/v1/charm/charm-name/resources/resource-name/oci-image/blob",
            {"image-digest": "a-very-specific-digest"},
            parse_json=False,
        )
    ]
    assert result == "some opaque stuff"
