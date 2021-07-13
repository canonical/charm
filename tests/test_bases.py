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


from unittest.mock import patch

import pytest

from charmcraft.config import Base
from charmcraft.bases import check_if_base_matches_host, get_host_as_base
from charmcraft.utils import OSPlatform


@pytest.fixture
def mock_get_os_platform():
    os_platform = OSPlatform(system="host-OS", release="host-CHANNEL", machine="host-ARCH")
    with patch("charmcraft.bases.get_os_platform", return_value=os_platform) as mock_platform:
        yield mock_platform


@pytest.fixture
def mock_get_host_architecture():
    with patch(
        "charmcraft.bases.get_host_architecture", return_value="host-ARCH"
    ) as mock_host_arch:
        yield mock_host_arch


def test_get_host_as_base(mock_get_os_platform, mock_get_host_architecture):
    assert get_host_as_base() == Base(
        name="host-os",
        channel="host-CHANNEL",
        architectures=["host-ARCH"],
    )


def test_check_if_bases_matches_host_matches(mock_get_os_platform, mock_get_host_architecture):
    base = Base(name="host-os", channel="host-CHANNEL", architectures=["host-ARCH"])
    assert check_if_base_matches_host(base) == (True, None)

    base = Base(
        name="host-os",
        channel="host-CHANNEL",
        architectures=["other-ARCH", "host-ARCH"],
    )
    assert check_if_base_matches_host(base) == (True, None)


def test_check_if_bases_matches_host_name_mismatch(
    mock_get_os_platform, mock_get_host_architecture
):
    base = Base(name="test-other-os", channel="host-CHANNEL", architectures=["host-ARCH"])

    assert check_if_base_matches_host(base) == (
        False,
        "name 'test-other-os' does not match host 'host-os'",
    )


def test_check_if_bases_matches_host_channel_mismatch(
    mock_get_os_platform, mock_get_host_architecture
):
    base = Base(name="host-os", channel="other-CHANNEL", architectures=["host-ARCH"])

    assert check_if_base_matches_host(base) == (
        False,
        "channel 'other-CHANNEL' does not match host 'host-CHANNEL'",
    )


def test_check_if_bases_matches_host_arch_mismatch(
    mock_get_os_platform, mock_get_host_architecture
):
    base = Base(
        name="host-os",
        channel="host-CHANNEL",
        architectures=["other-ARCH", "other-ARCH2"],
    )

    assert check_if_base_matches_host(base) == (
        False,
        "host architecture 'host-ARCH' not in base architectures ['other-ARCH', 'other-ARCH2']",
    )
