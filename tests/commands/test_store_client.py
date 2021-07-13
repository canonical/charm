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

"""Tests for the Store client and authentication (code in store/client.py)."""

import json
import logging
import os
from http.cookiejar import MozillaCookieJar, Cookie
from unittest.mock import patch

import pytest
from macaroonbakery import httpbakery
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from charmcraft.cmdbase import CommandError
from charmcraft.commands.store.client import (
    Client,
    _AuthHolder,
    _storage_push,
    build_user_agent,
    visit_page_with_browser,
)
from charmcraft.utils import OSPlatform


# --- General tests


def test_useragent_linux(monkeypatch):
    """Construct a user-agent as a patched Linux machine"""
    monkeypatch.setenv("TRAVIS_TESTING", "1")
    os_platform = OSPlatform(system="Arch Linux", release="5.10.10-arch1-1", machine="x86_64")
    with patch("charmcraft.commands.store.client.__version__", "1.2.3"), patch(
        "charmcraft.utils.get_os_platform", return_value=os_platform
    ), patch("platform.system", return_value="Linux"), patch(
        "platform.machine", return_value="x86_64"
    ), patch(
        "platform.python_version", return_value="3.9.1"
    ):
        ua = build_user_agent()
    assert ua == "charmcraft/1.2.3 (testing) Arch Linux/5.10.10-arch1-1 (x86_64) python/3.9.1"


def test_useragent_windows(monkeypatch):
    """Construct a user-agent as a patched Windows machine"""
    monkeypatch.setenv("TRAVIS_TESTING", "1")
    with patch("charmcraft.commands.store.client.__version__", "1.2.3"), patch(
        "platform.system", return_value="Windows"
    ), patch("platform.release", return_value="10"), patch(
        "platform.machine", return_value="AMD64"
    ), patch(
        "platform.python_version", return_value="3.9.1"
    ):
        ua = build_user_agent()
    assert ua == "charmcraft/1.2.3 (testing) Windows/10 (AMD64) python/3.9.1"


# --- AuthHolder tests


@pytest.fixture
def auth_holder(tmp_path):
    """Produce an _AuthHolder instance with encapsulated resources.

    In detail:

    - writes into a temp dir

    - with a mocked webbrowser module
    """

    ah = _AuthHolder()
    ah._cookiejar_filepath = str(tmp_path / "test.credentials")

    with patch("webbrowser.open"):
        yield ah


def get_cookie(value="test"):
    """Helper to create a cookie, which is quite long."""
    return Cookie(
        version=0,
        name="test-macaroon",
        value=value,
        port=None,
        port_specified=False,
        domain="snapcraft.io",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=2595425286,
        discard=False,
        comment=None,
        comment_url=None,
        rest=None,
        rfc2109=False,
    )


def test_authholder_cookiejar_filepath():
    """Builds the cookiejar filepath in user's config directory."""
    with patch("appdirs.user_config_dir") as mock:
        mock.return_value = "testpath"
        ah = _AuthHolder()

    assert ah._cookiejar_filepath == "testpath"
    mock.assert_called_once_with("charmcraft.credentials")


def test_authholder_clear_credentials_ok(auth_holder, caplog):
    """Clear credentials removes the file."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    with open(auth_holder._cookiejar_filepath, "wb") as fh:
        fh.write(b"fake credentials")

    auth_holder.clear_credentials()

    assert not os.path.exists(auth_holder._cookiejar_filepath)
    expected = "Credentials cleared: file {!r} removed".format(auth_holder._cookiejar_filepath)
    assert [expected] == [rec.message for rec in caplog.records]


def test_authholder_clear_credentials_missing(auth_holder, caplog):
    """Clear credentials supports the file not being there."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    auth_holder.clear_credentials()

    assert not os.path.exists(auth_holder._cookiejar_filepath)
    expected = "Credentials file not found to be removed: {!r}".format(
        auth_holder._cookiejar_filepath
    )
    assert [expected] == [rec.message for rec in caplog.records]


def test_authholder_credentials_load_file_present_ok(auth_holder):
    """Credentials are properly loaded and all internal objects setup ok."""
    # create some fake cookies
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookie = get_cookie()
    fake_cookiejar.set_cookie(fake_cookie)
    fake_cookiejar.save()

    auth_holder._load_credentials()

    # check credentials
    loaded_cookies = list(auth_holder._cookiejar)
    assert len(loaded_cookies) == 1
    assert loaded_cookies[0].value == fake_cookie.value  # compare the value as no __eq__ in Cookie
    assert isinstance(auth_holder._cookiejar, MozillaCookieJar)
    assert auth_holder._old_cookies == list(auth_holder._cookiejar)

    # check other internal objects
    assert isinstance(auth_holder._client, httpbakery.Client)
    assert list(auth_holder._client.cookies)[0].value == fake_cookie.value
    (im,) = auth_holder._client._interaction_methods
    assert isinstance(im, httpbakery.WebBrowserInteractor)
    assert im._open_web_browser == visit_page_with_browser


def test_authholder_credentials_load_file_present_problem(auth_holder, caplog):
    """Support the file to be corrupt (starts blank)."""
    caplog.set_level(logging.WARNING, logger="charmcraft.commands")

    with open(auth_holder._cookiejar_filepath, "wb") as fh:
        fh.write(b"this surely is not a valid cookie format :p")

    auth_holder._load_credentials()

    assert "Failed to read credentials" in caplog.records[0].message
    assert auth_holder._old_cookies == []


def test_authholder_credentials_load_file_missing(auth_holder, caplog):
    """Support the file to not be there (starts blank)."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    auth_holder._load_credentials()

    expected = "Credentials file not found: {!r}".format(auth_holder._cookiejar_filepath)
    assert [expected] == [rec.message for rec in caplog.records]
    assert auth_holder._old_cookies == []


def test_authholder_credentials_save_notreally(auth_holder):
    """Save does not really save if cookies didn't change."""
    # create some fake cookies
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookie = get_cookie()
    fake_cookiejar.set_cookie(fake_cookie)
    fake_cookiejar.save()

    auth_holder._load_credentials()

    with patch.object(auth_holder._cookiejar, "save") as mock:
        auth_holder._save_credentials_if_changed()
    assert mock.call_count == 0


def test_authholder_credentials_save_reallysave(auth_holder):
    """Save really do save if cookies changed."""
    # create some fake cookies
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookie = get_cookie()
    fake_cookiejar.set_cookie(fake_cookie)
    fake_cookiejar.save()

    # make auth holder to have those credentials loaded, and also load them ourselves for
    # later comparison
    auth_holder._load_credentials()
    with open(auth_holder._cookiejar_filepath, "rb") as fh:
        prv_file_content = fh.read()

    # set a different credential in the auth_holder (mimickin that the user authenticated
    # while doing the request)
    other_cookie = get_cookie(value="different")
    auth_holder._cookiejar.set_cookie(other_cookie)

    # call the tested method and ensure that file changed!
    auth_holder._save_credentials_if_changed()
    with open(auth_holder._cookiejar_filepath, "rb") as fh:
        new_file_content = fh.read()
    assert new_file_content != prv_file_content

    # call the tested method again, to verify that it was calling save on the cookiejar (and
    # not that the file changed as other side effect)
    with patch.object(auth_holder._cookiejar, "save") as mock:
        auth_holder._save_credentials_if_changed()
    assert mock.call_count == 1


def test_authholder_credentials_save_createsdir(auth_holder, tmp_path):
    """Save creates the directory if not there."""
    weird_filepath = tmp_path / "not_created_dir" / "deep" / "credentials"
    auth_holder._cookiejar_filepath = str(weird_filepath)
    auth_holder._load_credentials()

    # set a cookie and ask for saving it
    auth_holder._cookiejar.set_cookie(get_cookie(value="different"))
    auth_holder._save_credentials_if_changed()

    # file should be there, and have the right permissions
    assert weird_filepath.exists()
    assert os.stat(str(weird_filepath)).st_mode & 0o777 == 0o600


def test_authholder_request_simple(auth_holder):
    """Load credentials the first time, hit the network, save credentials."""
    # save a cookie to be used
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookiejar.set_cookie(get_cookie())
    fake_cookiejar.save()

    other_cookie = get_cookie(value="different")

    def fake_request(self, method, url, json, headers):
        # check it was properly called
        assert method == "testmethod"
        assert url == "testurl"
        assert json == "testbody"
        assert headers == {"User-Agent": build_user_agent()}

        # check credentials were loaded at this time
        assert auth_holder._cookiejar is not None

        # modify the credentials, to simulate that a re-auth happened while the request
        auth_holder._cookiejar.set_cookie(other_cookie)

        return "raw request response"

    with patch("macaroonbakery.httpbakery.Client.request", fake_request):
        resp = auth_holder.request("testmethod", "testurl", "testbody")

    # verify response (the calling checks were done above in fake_request helper)
    assert resp == "raw request response"

    # check the credentials were saved (that were properly loaded was also check in above's helper)
    new_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    new_cookiejar.load()
    assert list(new_cookiejar)[0].value == other_cookie.value


def test_authholder_request_credentials_already_loaded(auth_holder):
    """Do not load credentials if already there."""
    # save a cookie to be used
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookiejar.set_cookie(get_cookie())
    fake_cookiejar.save()

    # load credentials, and ensure that this will be fail if it's called again
    auth_holder._load_credentials()
    auth_holder._load_credentials = None

    with patch("macaroonbakery.httpbakery.Client.request"):
        auth_holder.request("testmethod", "testurl", "testbody")


def test_authholder_request_interaction_error(auth_holder):
    """Support authentication failure while doing the request."""
    # save a cookie to be used
    fake_cookiejar = MozillaCookieJar(auth_holder._cookiejar_filepath)
    fake_cookiejar.set_cookie(get_cookie())
    fake_cookiejar.save()

    with patch("macaroonbakery.httpbakery.Client.request") as mock:
        mock.side_effect = httpbakery.InteractionError("bad auth!!")
        expected = "Authentication failure: cannot start interactive session: bad auth!!"
        with pytest.raises(CommandError, match=expected):
            auth_holder.request("testmethod", "testurl", "testbody")


# --- Client tests


class FakeResponse:
    def __init__(self, content, status_code):
        self.content = content
        self.status_code = status_code

    @property
    def ok(self):
        return self.status_code == 200

    def json(self):
        return json.loads(self.content)

    @property
    def text(self):
        return self.content


def test_client_get():
    """Passes the correct method."""
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        client = Client("http://api.test", "http://storage.test")
    client.get("/somepath")

    mock_auth().request.assert_called_once_with("GET", "http://api.test/somepath", None)


def test_client_post():
    """Passes the correct method."""
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        client = Client("http://api.test", "http://storage.test")
    client.post("/somepath", "somebody")

    mock_auth().request.assert_called_once_with("POST", "http://api.test/somepath", "somebody")


def test_client_hit_success_simple(caplog):
    """Hits the server, all ok."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    response_value = {"foo": "bar"}
    fake_response = FakeResponse(content=json.dumps(response_value), status_code=200)
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        mock_auth().request.return_value = fake_response
        client = Client("http://api.test", "http://storage.test")
    result = client._hit("GET", "/somepath")

    mock_auth().request.assert_called_once_with("GET", "http://api.test/somepath", None)
    assert result == response_value
    expected = [
        "Hitting the store: GET http://api.test/somepath None",
        "Store ok: 200",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_client_hit_success_without_json_parsing():
    """Hits the server, all ok, return the raw response without parsing the json."""
    response_value = "whatever test response"
    fake_response = FakeResponse(content=response_value, status_code=200)
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        mock_auth().request.return_value = fake_response
        client = Client("http://api.test", "http://storage.test")
    result = client._hit("GET", "/somepath", parse_json=False)

    mock_auth().request.assert_called_once_with("GET", "http://api.test/somepath", None)
    assert result == response_value


def test_client_hit_url_extra_slash():
    """The configured api url is ok even with an extra slash."""
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        client = Client("https://local.test:1234/", "http://storage.test")
    client._hit("GET", "/somepath")
    mock_auth().request.assert_called_once_with("GET", "https://local.test:1234/somepath", None)


def test_client_hit_success_withbody(caplog):
    """Hits the server including a body, all ok."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    response_value = {"foo": "bar"}
    fake_response = FakeResponse(content=json.dumps(response_value), status_code=200)
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        mock_auth().request.return_value = fake_response
        client = Client("http://api.test", "http://storage.test")
    result = client._hit("POST", "/somepath", "somebody")

    mock_auth().request.assert_called_once_with("POST", "http://api.test/somepath", "somebody")
    assert result == response_value
    expected = [
        "Hitting the store: POST http://api.test/somepath somebody",
        "Store ok: 200",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_client_hit_failure():
    """Hits the server, got a failure."""
    response_value = "raw data"
    fake_response = FakeResponse(content=response_value, status_code=404)
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        mock_auth().request.return_value = fake_response
        client = Client("http://api.test", "http://storage.test")

    expected = r"Failure working with the Store: \[404\] 'raw data'"
    with pytest.raises(CommandError, match=expected):
        client._hit("GET", "/somepath")


def test_client_clear_credentials():
    with patch("charmcraft.commands.store.client._AuthHolder") as mock_auth:
        client = Client("http://api.test", "http://storage.test")
    client.clear_credentials()

    mock_auth().clear_credentials.assert_called_once_with()


def test_client_errorparsing_complete():
    """Build the error message using original message and code."""
    content = json.dumps({"error-list": [{"message": "error message", "code": "test-error"}]})
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Store failure! error message [code: test-error]"


def test_client_errorparsing_no_code():
    """Build the error message using original message (even when code in None)."""
    content = json.dumps({"error-list": [{"message": "error message", "code": None}]})
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Store failure! error message"


def test_client_errorparsing_multiple():
    """Build the error message coumpounding the different received ones."""
    content = json.dumps(
        {
            "error-list": [
                {"message": "error 1", "code": "test-error-1"},
                {"message": "error 2", "code": None},
            ]
        }
    )
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Store failure! error 1 [code: test-error-1]; error 2"


def test_client_errorparsing_nojson():
    """Produce a default message if response is not a json."""
    response = FakeResponse(content="this is not a json", status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Failure working with the Store: [404] 'this is not a json'"


def test_client_errorparsing_no_errors_inside():
    """Produce a default message if response has no errors list."""
    content = json.dumps({"another-error-key": "stuff"})
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Failure working with the Store: [404] " + repr(content)


def test_client_errorparsing_empty_errors():
    """Produce a default message if error list is empty."""
    content = json.dumps({"error-list": []})
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Failure working with the Store: [404] " + repr(content)


def test_client_errorparsing_bad_structure():
    """Produce a default message if error list has a bad format."""
    content = json.dumps({"error-list": ["whatever"]})
    response = FakeResponse(content=content, status_code=404)
    result = Client("http://api.test", "http://storage.test")._parse_store_error(response)
    assert result == "Failure working with the Store: [404] " + repr(content)


def test_client_push_simple_ok(caplog, tmp_path, capsys):
    """Happy path for pushing bytes."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")

    # fake some bytes to push
    test_filepath = tmp_path / "supercharm.bin"
    with test_filepath.open("wb") as fh:
        fh.write(b"abcdefgh")

    def fake_pusher(monitor, storage_base_url):
        """Push bytes in sequence, doing verifications in the middle."""
        assert storage_base_url == "http://storage.test"

        total_to_push = monitor.len  # not only the saved bytes, but also headers and stuff

        # one batch
        monitor.read(20)
        captured = capsys.readouterr()
        assert captured.out == "Uploading... {:.2f}%\r".format(100 * 20 / total_to_push)

        # another batch
        monitor.read(20)
        captured = capsys.readouterr()
        assert captured.out == "Uploading... {:.2f}%\r".format(100 * 40 / total_to_push)

        # check monitor is properly built
        assert isinstance(monitor.encoder, MultipartEncoder)
        filename, fh, ctype = monitor.encoder.fields["binary"]
        assert filename == "supercharm.bin"
        assert fh.name == str(test_filepath)
        assert ctype == "application/octet-stream"

        content = json.dumps(dict(successful=True, upload_id="test-upload-id"))
        return FakeResponse(content=content, status_code=200)

    with patch("charmcraft.commands.store.client._storage_push", fake_pusher):
        Client("http://api.test", "http://storage.test").push(test_filepath)

    # check proper logs
    expected = [
        "Starting to push {!r}".format(str(test_filepath)),
        "Uploading bytes ended, id test-upload-id",
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_client_push_configured_url_simple(tmp_path, capsys):
    """The storage server can be configured."""

    def fake_pusher(monitor, storage_base_url):
        """Check the received URL."""
        assert storage_base_url == "https://local.test:1234"

        content = json.dumps(dict(successful=True, upload_id="test-upload-id"))
        return FakeResponse(content=content, status_code=200)

    test_filepath = tmp_path / "supercharm.bin"
    test_filepath.write_text("abcdefgh")
    with patch("charmcraft.commands.store.client._storage_push", fake_pusher):
        Client("http://api.test", "https://local.test:1234/").push(test_filepath)


def test_client_push_configured_url_extra_slash(caplog, tmp_path, capsys):
    """The configured storage url is ok even with an extra slash."""

    def fake_pusher(monitor, storage_base_url):
        """Check the received URL."""
        assert storage_base_url == "https://local.test:1234"

        content = json.dumps(dict(successful=True, upload_id="test-upload-id"))
        return FakeResponse(content=content, status_code=200)

    test_filepath = tmp_path / "supercharm.bin"
    test_filepath.write_text("abcdefgh")
    with patch("charmcraft.commands.store.client._storage_push", fake_pusher):
        Client("http://api.test", "https://local.test:1234/").push(test_filepath)


def test_client_push_response_not_ok(tmp_path):
    """Didn't get a 200 from the Storage."""
    # fake some bytes to push
    test_filepath = tmp_path / "supercharm.bin"
    with test_filepath.open("wb") as fh:
        fh.write(b"abcdefgh")

    with patch("charmcraft.commands.store.client._storage_push") as mock:
        mock.return_value = FakeResponse(content="had a problem", status_code=500)
        with pytest.raises(CommandError) as cm:
            Client("http://api.test", "http://storage.test").push(test_filepath)
        assert str(cm.value) == "Failure while pushing file: [500] 'had a problem'"


def test_client_push_response_unsuccessful(tmp_path):
    """Didn't get a 200 from the Storage."""
    # fake some bytes to push
    test_filepath = tmp_path / "supercharm.bin"
    with test_filepath.open("wb") as fh:
        fh.write(b"abcdefgh")

    with patch("charmcraft.commands.store.client._storage_push") as mock:
        raw_content = dict(successful=False, upload_id=None)
        mock.return_value = FakeResponse(content=json.dumps(raw_content), status_code=200)
        with pytest.raises(CommandError) as cm:
            Client("http://api.test", "http://storage.test").push(test_filepath)
        expected = "Server error while pushing file: {'successful': False, 'upload_id': None}"
        assert str(cm.value) == expected


def test_storage_push_succesful():
    """Bytes are properly pushed to the Storage."""
    test_monitor = MultipartEncoderMonitor(
        MultipartEncoder(fields={"binary": ("filename", "somefile", "application/octet-stream")})
    )

    with patch("requests.Session") as mock:
        _storage_push(test_monitor, "http://test.url:0000")
    cm_session_mock = mock().__enter__()

    # check request was properly called
    url = "http://test.url:0000/unscanned-upload/"
    headers = {
        "Content-Type": test_monitor.content_type,
        "Accept": "application/json",
        "User-Agent": build_user_agent(),
    }
    cm_session_mock.post.assert_called_once_with(url, headers=headers, data=test_monitor)

    # check the retries were properly setup
    (protocol, adapter), _ = cm_session_mock.mount.call_args
    assert protocol == "https://"
    assert isinstance(adapter, HTTPAdapter)
    assert adapter.max_retries.backoff_factor == 2
    assert adapter.max_retries.total == 5
    assert adapter.max_retries.status_forcelist == [500, 502, 503, 504]


def test_storage_push_network_error():
    """A generic network error happened."""
    test_monitor = MultipartEncoderMonitor(
        MultipartEncoder(fields={"binary": ("filename", "somefile", "application/octet-stream")})
    )

    with patch("requests.Session.post") as mock:
        mock.side_effect = RequestException("naughty error")
        with pytest.raises(CommandError) as cm:
            _storage_push(test_monitor, "http://test.url:0000")
        expected = "Network error when pushing file: RequestException('naughty error')"
        assert str(cm.value) == expected
