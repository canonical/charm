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

"""A client to hit the Store."""

import logging
import os
import platform
import webbrowser
from http.cookiejar import MozillaCookieJar

import appdirs
import requests
from macaroonbakery import httpbakery
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from requests.packages.urllib3.util.retry import Retry
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from charmcraft import __version__, utils
from charmcraft.cmdbase import CommandError

# set urllib3's logger to only emit errors, not warnings. Otherwise even
# retries are printed, and they're nasty.
logging.getLogger(requests.packages.urllib3.__package__).setLevel(logging.ERROR)

logger = logging.getLogger("charmcraft.commands.store")

TESTING_ENV_PREFIXES = ["TRAVIS", "AUTOPKGTEST_TMP"]


def build_user_agent():
    """Build the charmcraft's user agent."""
    if any(key.startswith(prefix) for prefix in TESTING_ENV_PREFIXES for key in os.environ.keys()):
        testing = " (testing) "
    else:
        testing = " "
    os_platform = "{0.system}/{0.release} ({0.machine})".format(utils.get_os_platform())
    return "charmcraft/{}{}{} python/{}".format(
        __version__, testing, os_platform, platform.python_version()
    )


def visit_page_with_browser(visit_url):
    """Open a browser so the user can validate its identity."""
    logger.warning(
        "Opening an authorization web page in your browser; if it does not open, "
        "please open this URL: %s",
        visit_url,
    )
    webbrowser.open(visit_url, new=1)


class _AuthHolder:
    """Holder and wrapper of all authentication bits.

    Main two purposes of this class:

    - deal with credentials persistence

    - wrap HTTP calls to ensure authentication
    """

    def __init__(self):
        self._cookiejar_filepath = appdirs.user_config_dir("charmcraft.credentials")
        self._cookiejar = None
        self._client = None

    def clear_credentials(self):
        """Clear stored credentials."""
        if os.path.exists(self._cookiejar_filepath):
            os.unlink(self._cookiejar_filepath)
            logger.debug("Credentials cleared: file %r removed", str(self._cookiejar_filepath))
        else:
            logger.debug(
                "Credentials file not found to be removed: %r",
                self._cookiejar_filepath,
            )

    def _save_credentials_if_changed(self):
        """Save credentials if changed."""
        if list(self._cookiejar) != self._old_cookies:
            logger.debug("Saving credentials to file: %r", str(self._cookiejar_filepath))
            dirpath = os.path.dirname(self._cookiejar_filepath)
            os.makedirs(dirpath, exist_ok=True)

            fd = os.open(self._cookiejar_filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            self._cookiejar.save(fd)

    def _load_credentials(self):
        """Load credentials and set up internal auth request objects."""
        wbi = httpbakery.WebBrowserInteractor(open=visit_page_with_browser)
        self._cookiejar = MozillaCookieJar(self._cookiejar_filepath)
        self._client = httpbakery.Client(cookies=self._cookiejar, interaction_methods=[wbi])

        if os.path.exists(self._cookiejar_filepath):
            logger.debug("Loading credentials from file: %r", str(self._cookiejar_filepath))
            try:
                self._cookiejar.load()
            except Exception as err:
                # alert and continue processing (without having credentials, of course, the user
                # will be asked to authenticate)
                logger.warning("Failed to read credentials: %r", err)
        else:
            logger.debug("Credentials file not found: %r", str(self._cookiejar_filepath))

        # iterates the cookiejar (which is mutable, may change later) and get the cookies
        # for comparison after hitting the endpoint
        self._old_cookies = list(self._cookiejar)

    def request(self, method, url, body):
        """Do a request."""
        if self._client is None:
            # load everything on first usage
            self._load_credentials()

        headers = {"User-Agent": build_user_agent()}

        # this request through the bakery lib will automatically catch any authentication
        # problem and (if any) ask the user to authenticate and retry the original request; if
        # that fails we capture it and raise a proper error
        try:
            resp = self._client.request(method, url, json=body, headers=headers)
        except httpbakery.InteractionError as err:
            raise CommandError("Authentication failure: {}".format(err))

        self._save_credentials_if_changed()
        return resp


def _storage_push(monitor, storage_base_url):
    """Push bytes to the storage."""
    url = storage_base_url + "/unscanned-upload/"
    headers = {
        "Content-Type": monitor.content_type,
        "Accept": "application/json",
        "User-Agent": build_user_agent(),
    }
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])

    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retries))

        try:
            response = session.post(url, headers=headers, data=monitor)
        except RequestException as err:
            raise CommandError(
                "Network error when pushing file: {}({!r})".format(
                    err.__class__.__name__, str(err)
                )
            )

    return response


class Client:
    """Lightweight layer above _AuthHolder to present a more network oriented interface."""

    def __init__(self, api_base_url, storage_base_url):
        self._auth_client = _AuthHolder()
        self.api_base_url = api_base_url.rstrip("/")
        self.storage_base_url = storage_base_url.rstrip("/")

    def clear_credentials(self):
        """Clear stored credentials."""
        self._auth_client.clear_credentials()

    def _parse_store_error(self, response):
        """Get the proper error from the Store response."""
        default_msg = "Failure working with the Store: [{}] {!r}".format(
            response.status_code, response.content
        )
        try:
            error_data = response.json()
        except ValueError:
            return default_msg

        try:
            error_info = [(error["message"], error["code"]) for error in error_data["error-list"]]
        except (KeyError, TypeError):
            return default_msg

        if not error_info:
            return default_msg

        messages = []
        for msg, code in error_info:
            if code:
                msg += " [code: {}]".format(code)
            messages.append(msg)
        return "Store failure! " + "; ".join(messages)

    def _hit(self, method, urlpath, body=None, parse_json=True):
        """Issue a request to the Store."""
        url = self.api_base_url + urlpath
        logger.debug("Hitting the store: %s %s %s", method, url, body)
        resp = self._auth_client.request(method, url, body)
        if not resp.ok:
            raise CommandError(self._parse_store_error(resp))

        logger.debug("Store ok: %s", resp.status_code)
        if parse_json:
            # XXX Facundo 2020-06-30: we need to wrap this .json() call, and raise UnknownError
            # (after logging in debug the received raw response). This would catch weird "html"
            # responses, for example, without making charmcraft to crash. Related: issue #73.
            data = resp.json()
        else:
            data = resp.text
        return data

    def get(self, *args, **kwargs):
        """GET something from the Store."""
        return self._hit("GET", *args, **kwargs)

    def post(self, *args, **kwargs):
        """POST a body (json-encoded) to the Store."""
        return self._hit("POST", *args, **kwargs)

    def push(self, filepath):
        """Push the bytes from filepath to the Storage."""
        logger.debug("Starting to push %r", str(filepath))

        def _progress(monitor):
            # XXX Facundo 2020-07-01: use a real progress bar
            if monitor.bytes_read <= monitor.len:
                progress = 100 * monitor.bytes_read / monitor.len
                print("Uploading... {:.2f}%\r".format(progress), end="", flush=True)

        with filepath.open("rb") as fh:
            encoder = MultipartEncoder(
                fields={"binary": (filepath.name, fh, "application/octet-stream")}
            )

            # create a monitor (so that progress can be displayed) as call the real pusher
            monitor = MultipartEncoderMonitor(encoder, _progress)
            response = _storage_push(monitor, self.storage_base_url)

        if not response.ok:
            raise CommandError(
                "Failure while pushing file: [{}] {!r}".format(
                    response.status_code, response.content
                )
            )

        result = response.json()
        if not result["successful"]:
            raise CommandError("Server error while pushing file: {}".format(result))

        upload_id = result["upload_id"]
        logger.debug("Uploading bytes ended, id %s", upload_id)
        return upload_id
