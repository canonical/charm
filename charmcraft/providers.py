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

"""Build environment provider support for charmcraft."""

import contextlib
import logging
import os
import pathlib
import re
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple, Union

from craft_providers import Executor, bases, lxd
from craft_providers.actions import snap_installer
from craft_providers.lxd import LXDInstallationError
from craft_providers.lxd import installer as lxd_installer
from craft_providers.lxd.remotes import configure_buildd_image_remote

from charmcraft.cmdbase import CommandError
from charmcraft.config import Base
from charmcraft.env import (
    get_managed_environment_log_path,
    get_managed_environment_project_path,
)
from charmcraft.utils import confirm_with_user, get_host_architecture

logger = logging.getLogger(__name__)

BASE_CHANNEL_TO_BUILDD_IMAGE_ALIAS = {
    "18.04": bases.BuilddBaseAlias.BIONIC,
    "20.04": bases.BuilddBaseAlias.FOCAL,
}


def capture_logs_from_instance(instance: Executor) -> None:
    """Retrieve logs from instance.

    :param instance: Instance to retrieve logs from.

    :returns: String of logs.
    """
    _, tmp_path = tempfile.mkstemp(prefix="charmcraft-")
    local_log_path = pathlib.Path(tmp_path)
    instance_log_path = get_managed_environment_log_path()

    try:
        instance.pull_file(source=instance_log_path, destination=local_log_path)
    except FileNotFoundError:
        logger.debug("No logs found in instance.")
        return

    logs = local_log_path.read_text()
    local_log_path.unlink()

    logger.debug("Logs captured from managed instance:\n%s", logs)


def clean_project_environments(
    charm_name: str,
    project_path: pathlib.Path,
    *,
    lxd_project: str = "charmcraft",
    lxd_remote: str = "local",
) -> List[str]:
    """Clean up any environments created for project.

    :param charm_name: Name of project.
    :param project_path: Directory of charm project.
    :param lxd_project: Name of LXD project.
    :param lxd_remote: Name of LXD remote.

    :returns: List of containers deleted.
    """
    deleted: List[str] = []

    # Nothing to do if provider is not installed.
    if not is_provider_available():
        return deleted

    inode = str(project_path.stat().st_ino)
    lxc = lxd.LXC()

    for name in lxc.list_names(project=lxd_project, remote=lxd_remote):
        match_regex = f"^charmcraft-{charm_name}-{inode}-.+-.+-.+$"
        if re.match(match_regex, name):
            logger.debug("Deleting container %r.", name)
            lxc.delete(instance_name=name, force=True, project=lxd_project, remote=lxd_remote)
            deleted.append(name)
        else:
            logger.debug("Not deleting container %r.", name)

    return deleted


def ensure_provider_is_available() -> None:
    """Ensure provider is available, prompting the user to install it if required.

    :raises CommandError: if provider is not available.
    """
    if is_provider_available():
        return

    if confirm_with_user(
        "LXD is required, but not installed. Do you wish to install LXD "
        "and configure it with the defaults?",
        default=False,
    ):
        try:
            lxd_installer.install()
        except LXDInstallationError as error:
            raise CommandError(
                "Failed to install LXD. Please visit https://snapcraft.io/lxd for "
                "instructions on how to install the LXD snap for your distribution"
            ) from error
    else:
        raise CommandError(
            "LXD is required, but not installed. Please visit https://snapcraft.io/lxd for "
            "instructions on how to install the LXD snap for your distribution"
        )


def is_base_providable(base: Base) -> Tuple[bool, Union[str, None]]:
    """Check if provider can provide an environment matching given base.

    :param base: Base to check.

    :returns: Tuple of bool indicating whether it is a match, with optional
              reason if not a match.
    """
    host_arch = get_host_architecture()
    if host_arch not in base.architectures:
        return (
            False,
            f"host architecture {host_arch!r} not in base architectures {base.architectures!r}",
        )

    if base.name != "ubuntu":
        return (
            False,
            f"name {base.name!r} is not yet supported (must be 'ubuntu')",
        )

    if base.channel not in BASE_CHANNEL_TO_BUILDD_IMAGE_ALIAS.keys():
        return (
            False,
            f"channel {base.channel!r} is not yet supported (must be '18.04' or '20.04')",
        )

    return True, None


def get_instance_name(
    *,
    bases_index: int,
    build_on_index: int,
    project_name: str,
    project_path: pathlib.Path,
    target_arch: str,
) -> str:
    """Formulate the name for an instance using each of the given parameters.

    Incorporate each of the parameters into the name to come up with a
    predictable naming schema that avoids name collisions across multiple,
    potentially complex, projects.

    :param bases_index: Index of `bases:` entry.
    :param build_on_index: Index of `build-on` within bases entry.
    :param project_name: Name of charm project.
    :param project_path: Directory of charm project.
    :param target_arch: Targetted architecture, used in the name to prevent
        collisions should future work enable multiple architectures on the same
        platform.
    """
    return "-".join(
        [
            "charmcraft",
            project_name,
            str(project_path.stat().st_ino),
            str(bases_index),
            str(build_on_index),
            target_arch,
        ]
    )


def get_command_environment() -> Dict[str, str]:
    """Construct the required environment."""
    env = bases.buildd.default_command_environment()
    env["CHARMCRAFT_MANAGED_MODE"] = "1"

    # Pass-through host environment that target may need.
    for env_key in ["http_proxy", "https_proxy", "no_proxy"]:
        if env_key in os.environ:
            env[env_key] = os.environ[env_key]

    return env


def is_provider_available() -> bool:
    """Check if provider is installed and available for use.

    :returns: True if installed.
    """
    return lxd_installer.is_installed()


@contextlib.contextmanager
def launched_environment(
    *,
    charm_name: str,
    project_path: pathlib.Path,
    base: Base,
    bases_index: int,
    build_on_index: int,
    lxd_project: str = "charmcraft",
    lxd_remote: str = "local",
):
    """Launch environment for specified base.

    :param charm_name: Name of project.
    :param project_path: Path to project.
    :param base: Base to create.
    :param bases_index: Index of `bases:` entry.
    :param build_on_index: Index of `build-on` within bases entry.
    """
    alias = BASE_CHANNEL_TO_BUILDD_IMAGE_ALIAS[base.channel]
    target_arch = get_host_architecture()

    instance_name = get_instance_name(
        bases_index=bases_index,
        build_on_index=build_on_index,
        project_name=charm_name,
        project_path=project_path,
        target_arch=target_arch,
    )

    environment = get_command_environment()
    image_remote = configure_buildd_image_remote()
    base_configuration = CharmcraftBuilddBaseConfiguration(
        alias=alias, environment=environment, hostname=instance_name
    )
    instance = lxd.launch(
        name=instance_name,
        base_configuration=base_configuration,
        image_name=base.channel,
        image_remote=image_remote,
        auto_clean=True,
        auto_create_project=True,
        map_user_uid=True,
        use_snapshots=True,
        project=lxd_project,
        remote=lxd_remote,
    )

    # Mount project.
    instance.mount(host_source=project_path, target=get_managed_environment_project_path())

    try:
        yield instance
    finally:
        # Ensure to unmount everything and stop instance upon completion.
        instance.unmount_all()
        instance.stop()


class CharmcraftBuilddBaseConfiguration(bases.BuilddBase):
    """Base configuration for Charmcraft.

    :cvar compatibility_tag: Tag/Version for variant of build configuration and
        setup.  Any change to this version would indicate that prior [versioned]
        instances are incompatible and must be cleaned.  As such, any new value
        should be unique to old values (e.g. incrementing).  Charmcraft extends
        the buildd tag to include its own version indicator (.0) and namespace
        ("charmcraft").
    """

    compatibility_tag: str = f"charmcraft-{bases.BuilddBase.compatibility_tag}.0"

    def setup(
        self,
        *,
        executor: Executor,
        retry_wait: float = 0.25,
        timeout: Optional[float] = None,
    ) -> None:
        """Prepare base instance for use by the application.

        In addition to the guarantees provided by buildd:

            - charmcraft installed

            - python3 pip and setuptools installed

        :param executor: Executor for target container.
        :param retry_wait: Duration to sleep() between status checks (if
            required).
        :param timeout: Timeout in seconds.

        :raises BaseCompatibilityError: if instance is incompatible.
        :raises BaseConfigurationError: on other unexpected error.
        """
        super().setup(executor=executor, retry_wait=retry_wait, timeout=timeout)

        try:
            # XXX Patterson 2021-07-02: craft-parts will determine/install these
            # deps as a matter of the plugin(s) and source(s) being used.
            executor.execute_run(
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
            )
        except subprocess.CalledProcessError as error:
            raise bases.BaseConfigurationError(
                brief="Failed to install the required dependencies.",
            ) from error

        try:
            snap_installer.inject_from_host(
                executor=executor, snap_name="charmcraft", classic=True
            )
        except snap_installer.SnapInstallationError as error:
            raise bases.BaseConfigurationError(
                brief="Failed to inject host Charmcraft snap into target environment.",
            ) from error
