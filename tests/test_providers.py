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

import os
import pathlib
import re
import subprocess
from unittest import mock
from unittest.mock import call

import pytest
from craft_providers import Executor, bases
from craft_providers.actions import snap_installer
from craft_providers.lxd import LXDInstallationError

from charmcraft import providers
from charmcraft.cmdbase import CommandError
from charmcraft.config import Base


@pytest.fixture(autouse=True)
def bypass_buildd_base_setup(monkeypatch):
    """Patch out inherited setup steps."""
    monkeypatch.setattr(bases.BuilddBase, "setup", lambda *args, **kwargs: None)


@pytest.fixture()
def mock_configure_buildd_image_remote():
    with mock.patch(
        "charmcraft.providers.configure_buildd_image_remote",
        return_value="buildd-remote",
    ) as mock_remote:
        yield mock_remote


@pytest.fixture
def mock_confirm_with_user():
    with mock.patch(
        "charmcraft.providers.confirm_with_user",
        return_value=False,
    ) as mock_confirm:
        yield mock_confirm


@pytest.fixture
def mock_executor():
    yield mock.Mock(spec=Executor)


@pytest.fixture
def mock_logger():
    with mock.patch("charmcraft.providers.logger") as mock_logger:
        yield mock_logger


@pytest.fixture
def mock_lxc(monkeypatch):
    with mock.patch("charmcraft.providers.lxd.LXC", autospec=True) as mock_lxc:
        yield mock_lxc


@pytest.fixture
def mock_lxd(monkeypatch):
    with mock.patch("charmcraft.providers.lxd", autospec=True) as mock_lxd:
        yield mock_lxd


@pytest.fixture(autouse=True)
def mock_lxd_is_installed():
    with mock.patch(
        "charmcraft.providers.lxd_installer.is_installed", return_value=True
    ) as mock_is_installed:
        yield mock_is_installed


@pytest.fixture()
def mock_lxd_install():
    with mock.patch("charmcraft.providers.lxd_installer.install") as mock_install:
        yield mock_install


@pytest.fixture()
def mock_mkstemp():
    with mock.patch("charmcraft.providers.tempfile.mkstemp") as mock_mkstemp:
        yield mock_mkstemp


@pytest.fixture
def mock_inject():
    with mock.patch("craft_providers.actions.snap_installer.inject_from_host") as mock_inject:
        yield mock_inject


@pytest.fixture
def mock_path():
    mock_path = mock.Mock(spec=pathlib.Path)
    mock_path.stat.return_value.st_ino = 445566
    yield mock_path


@pytest.fixture(autouse=True)
def clear_environment(monkeypatch):
    monkeypatch.setattr(os, "environ", {})


@pytest.mark.parametrize("alias", [bases.BuilddBaseAlias.BIONIC, bases.BuilddBaseAlias.FOCAL])
def test_base_configuration_setup(mock_executor, mock_inject, monkeypatch, alias):

    config = providers.CharmcraftBuilddBaseConfiguration(alias=alias)
    config.setup(executor=mock_executor)

    assert mock_executor.mock_calls == [
        call.execute_run(
            [
                "apt-get",
                "install",
                "-y",
                "git",
                "python3-pip",
                "python3-setuptools",
                "python3-wheel",
            ],
            check=True,
            capture_output=True,
        ),
    ]

    assert mock_inject.mock_calls == [
        call(executor=mock_executor, snap_name="charmcraft", classic=True)
    ]

    assert config.compatibility_tag == "charmcraft-buildd-base-v0.0"


def test_base_configuration_setup_apt_error(mock_executor):
    alias = bases.BuilddBaseAlias.FOCAL
    apt_cmd = ["apt-get", "install", "-y", "git", "python3-pip", "python3-setuptools"]
    mock_executor.execute_run.side_effect = subprocess.CalledProcessError(
        -1,
        apt_cmd,
        "some output",
        "some error",
    )

    config = providers.CharmcraftBuilddBaseConfiguration(alias=alias)

    with pytest.raises(
        bases.BaseConfigurationError,
        match=r"Failed to install the required dependencies.",
    ) as exc_info:
        config.setup(executor=mock_executor)

    assert exc_info.value.__cause__ is not None


def test_base_configuration_setup_snap_injection_error(mock_executor, mock_inject):
    alias = bases.BuilddBaseAlias.FOCAL
    config = providers.CharmcraftBuilddBaseConfiguration(alias=alias)
    mock_inject.side_effect = snap_installer.SnapInstallationError(brief="foo error")

    with pytest.raises(
        bases.BaseConfigurationError,
        match=r"Failed to inject host Charmcraft snap into target environment.",
    ) as exc_info:
        config.setup(executor=mock_executor)

    assert exc_info.value.__cause__ is not None


def test_capture_logs_from_instance(mock_executor, mock_logger, mock_mkstemp, tmp_path):
    fake_log = tmp_path / "x.log"
    mock_mkstemp.return_value = (None, str(fake_log))

    fake_log_data = "some\nlog data\nhere"
    fake_log.write_text(fake_log_data)

    providers.capture_logs_from_instance(mock_executor)

    assert mock_executor.mock_calls == [
        mock.call.pull_file(source=pathlib.Path("/tmp/charmcraft.log"), destination=fake_log),
    ]
    assert mock_logger.mock_calls == [
        mock.call.debug("Logs captured from managed instance:\n%s", fake_log_data)
    ]


def test_capture_logs_from_instance_not_found(mock_executor, mock_logger, mock_mkstemp, tmp_path):
    fake_log = tmp_path / "x.log"
    mock_mkstemp.return_value = (None, str(fake_log))
    mock_executor.pull_file.side_effect = FileNotFoundError()

    providers.capture_logs_from_instance(mock_executor)

    assert mock_executor.mock_calls == [
        mock.call.pull_file(source=pathlib.Path("/tmp/charmcraft.log"), destination=fake_log),
    ]
    assert mock_logger.mock_calls == [mock.call.debug("No logs found in instance.")]


def test_clean_project_environments_without_lxd(mock_lxc, mock_lxd_is_installed, mock_path):
    mock_lxd_is_installed.return_value = False

    assert (
        providers.clean_project_environments(
            charm_name="my-charm",
            project_path=mock_path,
            lxd_project="test-project",
            lxd_remote="test-remote",
        )
        == []
    )

    assert mock_lxd_is_installed.mock_calls == [mock.call()]
    assert mock_lxc.mock_calls == []


def test_clean_project_environments(mock_lxc, mock_path):
    mock_lxc.return_value.list_names.return_value = [
        "do-not-delete-me-please",
        "charmcraft-testcharm-445566-b-c-d",
        "charmcraft-my-charm---",
        "charmcraft-my-charm-445566---",
        "charmcraft-my-charm-project-445566-0-0-amd99",
        "charmcraft-my-charm-project-445566-999-444-arm64",
        "charmcraft_445566_a_b_c_d",
    ]

    assert providers.clean_project_environments(
        charm_name="my-charm-project",
        project_path=mock_path,
        lxd_project="test-project",
        lxd_remote="test-remote",
    ) == [
        "charmcraft-my-charm-project-445566-0-0-amd99",
        "charmcraft-my-charm-project-445566-999-444-arm64",
    ]
    assert mock_lxc.mock_calls == [
        mock.call(),
        mock.call().list_names(project="test-project", remote="test-remote"),
        mock.call().delete(
            instance_name="charmcraft-my-charm-project-445566-0-0-amd99",
            force=True,
            project="test-project",
            remote="test-remote",
        ),
        mock.call().delete(
            instance_name="charmcraft-my-charm-project-445566-999-444-arm64",
            force=True,
            project="test-project",
            remote="test-remote",
        ),
    ]

    mock_lxc.reset_mock()

    assert providers.clean_project_environments(
        charm_name="testcharm",
        project_path=mock_path,
        lxd_project="test-project",
        lxd_remote="test-remote",
    ) == [
        "charmcraft-testcharm-445566-b-c-d",
    ]
    assert mock_lxc.mock_calls == [
        mock.call(),
        mock.call().list_names(project="test-project", remote="test-remote"),
        mock.call().delete(
            instance_name="charmcraft-testcharm-445566-b-c-d",
            force=True,
            project="test-project",
            remote="test-remote",
        ),
    ]

    mock_lxc.reset_mock()

    assert (
        providers.clean_project_environments(
            charm_name="unknown-charm",
            project_path=mock_path,
            lxd_project="test-project",
            lxd_remote="test-remote",
        )
        == []
    )
    assert mock_lxc.mock_calls == [
        mock.call(),
        mock.call().list_names(project="test-project", remote="test-remote"),
    ]


def test_ensure_provider_is_available_ok_when_installed(mock_lxd_is_installed):
    mock_lxd_is_installed.return_value = True
    providers.ensure_provider_is_available()


def test_ensure_provider_is_available_errors_when_user_declines(
    mock_confirm_with_user, mock_lxd_is_installed
):
    mock_confirm_with_user.return_value = False
    mock_lxd_is_installed.return_value = False

    with pytest.raises(
        CommandError,
        match=re.escape(
            "LXD is required, but not installed. Please visit https://snapcraft.io/lxd for "
            "instructions on how to install the LXD snap for your distribution"
        ),
    ):
        providers.ensure_provider_is_available()

    assert mock_confirm_with_user.mock_calls == [
        mock.call(
            "LXD is required, but not installed. "
            "Do you wish to install LXD and configure it with the defaults?",
            default=False,
        )
    ]


def test_ensure_provider_is_available_errors_when_lxd_install_fails(
    mock_confirm_with_user, mock_lxd_is_installed, mock_lxd_install
):
    mock_confirm_with_user.return_value = True
    mock_lxd_is_installed.return_value = False
    mock_lxd_install.side_effect = LXDInstallationError("foo")

    with pytest.raises(
        CommandError,
        match=re.escape(
            "Failed to install LXD. Please visit https://snapcraft.io/lxd for "
            "instructions on how to install the LXD snap for your distribution"
        ),
    ) as exc_info:
        providers.ensure_provider_is_available()

    assert mock_confirm_with_user.mock_calls == [
        mock.call(
            "LXD is required, but not installed. "
            "Do you wish to install LXD and configure it with the defaults?",
            default=False,
        )
    ]
    assert exc_info.value.__cause__ == mock_lxd_install.side_effect


def test_get_command_environment_minimal(monkeypatch):
    monkeypatch.setenv("IGNORE_ME", "or-im-failing")
    monkeypatch.setenv("PATH", "not-using-host-path")

    env = providers.get_command_environment()

    assert env == {
        "CHARMCRAFT_MANAGED_MODE": "1",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin",
    }


def test_get_command_environment_all_opts(monkeypatch):
    monkeypatch.setenv("IGNORE_ME", "or-im-failing")
    monkeypatch.setenv("PATH", "not-using-host-path")
    monkeypatch.setenv("http_proxy", "test-http-proxy")
    monkeypatch.setenv("https_proxy", "test-https-proxy")
    monkeypatch.setenv("no_proxy", "test-no-proxy")

    env = providers.get_command_environment()

    assert env == {
        "CHARMCRAFT_MANAGED_MODE": "1",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin",
        "http_proxy": "test-http-proxy",
        "https_proxy": "test-https-proxy",
        "no_proxy": "test-no-proxy",
    }


@pytest.mark.parametrize(
    "bases_index,build_on_index,project_name,target_arch,expected",
    [
        (0, 0, "mycharm", "test-arch1", "charmcraft-mycharm-{inode}-0-0-test-arch1"),
        (
            1,
            2,
            "my-other-charm",
            "test-arch2",
            "charmcraft-my-other-charm-{inode}-1-2-test-arch2",
        ),
    ],
)
def test_get_instance_name(
    bases_index, build_on_index, project_name, target_arch, expected, mock_path
):
    assert (
        providers.get_instance_name(
            bases_index=bases_index,
            build_on_index=build_on_index,
            project_name=project_name,
            project_path=mock_path,
            target_arch=target_arch,
        )
        == expected.format(inode="445566")
    )


@pytest.mark.parametrize(
    "name,channel,architectures,expected_valid,expected_reason",
    [
        ("ubuntu", "18.04", ["host-arch"], True, None),
        ("ubuntu", "20.04", ["host-arch"], True, None),
        ("ubuntu", "20.04", ["extra-arch", "host-arch"], True, None),
        (
            "not-ubuntu",
            "20.04",
            ["host-arch"],
            False,
            "name 'not-ubuntu' is not yet supported (must be 'ubuntu')",
        ),
        (
            "ubuntu",
            "10.04",
            ["host-arch"],
            False,
            "channel '10.04' is not yet supported (must be '18.04' or '20.04')",
        ),
        (
            "ubuntu",
            "20.04",
            ["other-arch"],
            False,
            "host architecture 'host-arch' not in base architectures ['other-arch']",
        ),
    ],
)
def test_is_base_providable(
    monkeypatch, name, channel, architectures, expected_valid, expected_reason
):
    monkeypatch.setattr(providers, "get_host_architecture", lambda: "host-arch")
    base = Base(name=name, channel=channel, architectures=architectures)

    valid, reason = providers.is_base_providable(base)

    assert (valid, reason) == (expected_valid, expected_reason)


@pytest.mark.parametrize("is_installed", [True, False])
def test_is_provider_available(is_installed):
    with mock.patch("charmcraft.providers.lxd_installer.is_installed", return_value=is_installed):
        assert providers.is_provider_available() == is_installed


@pytest.mark.parametrize(
    "channel,alias",
    [("18.04", bases.BuilddBaseAlias.BIONIC), ("20.04", bases.BuilddBaseAlias.FOCAL)],
)
def test_launched_environment(
    channel,
    alias,
    mock_configure_buildd_image_remote,
    mock_lxd,
    monkeypatch,
    tmp_path,
    mock_path,
):
    expected_environment = {
        "CHARMCRAFT_MANAGED_MODE": "1",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin",
    }

    monkeypatch.setattr(providers, "get_host_architecture", lambda: "host-arch")
    base = Base(name="ubuntu", channel=channel, architectures=["host-arch"])

    with mock.patch("charmcraft.providers.CharmcraftBuilddBaseConfiguration") as mock_base_config:
        with providers.launched_environment(
            charm_name="test-charm",
            project_path=mock_path,
            base=base,
            bases_index=1,
            build_on_index=2,
            lxd_project="charmcraft",
            lxd_remote="local",
        ) as instance:
            assert instance is not None
            assert mock_configure_buildd_image_remote.mock_calls == [mock.call()]
            assert mock_lxd.mock_calls == [
                mock.call.launch(
                    name="charmcraft-test-charm-445566-1-2-host-arch",
                    base_configuration=mock_base_config.return_value,
                    image_name=channel,
                    image_remote="buildd-remote",
                    auto_clean=True,
                    auto_create_project=True,
                    map_user_uid=True,
                    use_snapshots=True,
                    project="charmcraft",
                    remote="local",
                ),
                mock.call.launch().mount(
                    host_source=mock_path, target=pathlib.Path("/root/project")
                ),
            ]
            assert mock_base_config.mock_calls == [
                call(
                    alias=alias,
                    environment=expected_environment,
                    hostname="charmcraft-test-charm-445566-1-2-host-arch",
                )
            ]

            mock_lxd.reset_mock()

        assert mock_lxd.mock_calls == [
            mock.call.launch().unmount_all(),
            mock.call.launch().stop(),
        ]


def test_launched_environment_unmounts_and_stops_after_error(
    mock_configure_buildd_image_remote, mock_lxd, monkeypatch, tmp_path
):
    monkeypatch.setattr(providers, "get_host_architecture", lambda: "host-arch")
    base = Base(name="ubuntu", channel="20.04", architectures=["host-arch"])

    with pytest.raises(RuntimeError):
        with mock.patch("charmcraft.providers.CharmcraftBuilddBaseConfiguration"):
            with providers.launched_environment(
                charm_name="test-charm",
                project_path=tmp_path,
                base=base,
                bases_index=1,
                build_on_index=2,
                lxd_project="charmcraft",
                lxd_remote="local",
            ):
                mock_lxd.reset_mock()
                raise RuntimeError("this is a test")

    assert mock_lxd.mock_calls == [
        mock.call.launch().unmount_all(),
        mock.call.launch().stop(),
    ]
