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

import logging
from unittest import mock

import pytest

from charmcraft.commands.clean import CleanCommand


@pytest.fixture(autouse=True)
def mock_clean_project_environments():
    with mock.patch(
        "charmcraft.commands.clean.clean_project_environments", return_value=[]
    ) as mock_clean_project_environments:
        yield mock_clean_project_environments


def test_clean(caplog, caplog_filter, config, mock_clean_project_environments, tmp_path):
    logger_name = "charmcraft.commands.clean"
    caplog.set_level(logging.DEBUG, logger=logger_name)

    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text("name: foo")

    cmd = CleanCommand("group", "config")
    cmd.config = config
    cmd.run([])

    assert caplog_filter(logger_name) == [
        (logging.DEBUG, "Cleaning project 'foo'."),
        (logging.INFO, "Cleaned project 'foo'."),
    ]
    assert mock_clean_project_environments.mock_calls == [mock.call("foo", tmp_path)]
