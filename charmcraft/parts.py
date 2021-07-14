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

"""Craft-parts setup, lifecycle and plugins."""

import logging
import pathlib
import shlex
from typing import Any, Dict, List, Set, cast

from craft_parts import LifecycleManager, Step, plugins
from craft_parts.parts import PartSpec
from craft_parts.errors import PartsError
from xdg import BaseDirectory  # type: ignore

from charmcraft.cmdbase import CommandError

logger = logging.getLogger(__name__)


class CharmPluginProperties(plugins.PluginProperties, plugins.PluginModel):
    """Properties used in charm building."""

    source: str = ""
    charm_entrypoint: str = "src/charm.py"
    charm_requirements: List[str] = []
    charm_python_packages: List[str] = []
    charm_allow_pip_binary: bool = False

    @classmethod
    def unmarshal(cls, data: Dict[str, Any]):
        """Populate charm properties from the part specification.

        :param data: A dictionary containing part properties.

        :return: The populated plugin properties data object.

        :raise pydantic.ValidationError: If validation fails.
        """
        plugin_data = plugins.extract_plugin_properties(
            data, plugin_name="charm", required=["source"]
        )
        return cls(**plugin_data)


class CharmPlugin(plugins.Plugin):
    """Build the charm and prepare for packing.

    The craft-parts charm plugin installs python packages and requirements
    if specified, and prepares the charm payload for packing. Common plugin
    and source keywords can be used, as well as the following plugin-specific
    properties:

      - ``charm-entrypoint``
        (string)
        The path to the main charm executable, relative to the charm root.

      - ``charm-requirements``
        (list of strings)
        List of paths to requirements files.

      - ``charm-python-packages``
        (list of strings)
        A list of dependencies to get from PyPI.

      - ``charm-allow-pip-binary``
        (bool)
        Allow pip to install of binary wheels.

    Extra files to be included in the charm payload must be listed under
    the ``prime`` file filter.
    """

    properties_class = CharmPluginProperties

    @classmethod
    def get_build_snaps(cls) -> Set[str]:
        """Return a set of required snaps to install in the build environment."""
        return set()

    def get_build_packages(self) -> Set[str]:
        """Return a set of required packages to install in the build environment."""
        return {
            "python3-dev",
            "python3-venv",
            "python3-pip",
            "python3-setuptools",
            "python3-wheel",
        }

    def get_build_environment(self) -> Dict[str, str]:
        """Return a dictionary with the environment to use in the build step."""
        venv_dir = self._part_info.part_install_dir / self._part_info.venv_dir
        return {
            "PATH": "{}/bin:${{PATH}}".format(str(venv_dir)),
        }

    def get_build_commands(self) -> List[str]:
        """Return a list of commands to run during the build step."""
        venv_dir = self._part_info.part_install_dir / self._part_info.venv_dir
        pip_install_cmd = f"pip install --target={venv_dir}"
        options = cast(CharmPluginProperties, self._options)
        commands = []

        if not options.charm_allow_pip_binary:
            pip_install_cmd += " --no-binary :all:"

        if options.charm_python_packages:
            python_packages = " ".join(
                [shlex.quote(pkg) for pkg in options.charm_python_packages]
            )
            python_packages_cmd = f"{pip_install_cmd} {python_packages}"
            commands.append(python_packages_cmd)

        if options.charm_requirements:
            requirements = " ".join(f"-r {r!r}" for r in options.charm_requirements)
            requirements_cmd = f"{pip_install_cmd} {requirements}"
            commands.append(requirements_cmd)

        install_dir = self._part_info.part_install_dir
        commands.append(
            'cp --archive --link --no-dereference . "{}"'.format(install_dir)
        )

        return commands


def setup_parts():
    """Initialize craft-parts plugins."""
    plugins.register({"charm": CharmPlugin})


def validate_part(data: Dict[str, Any]) -> None:
    """Validate the given part data against common and plugin models.

    :param data: The part data to validate.
    """
    if not isinstance(data, dict):
        raise TypeError("value must be a dictionary")

    # copy the original data, we'll modify it
    spec = data.copy()

    plugin_name = spec.get("plugin", "")
    if not plugin_name:
        raise ValueError("'plugin' not defined")

    plugin_class = plugins.get_plugin_class(plugin_name)

    # validate plugin properties
    plugin_class.properties_class.unmarshal(spec)

    # validate common part properties
    plugins.strip_plugin_properties(spec, plugin_name=plugin_name)
    PartSpec(**spec)


class PartsLifecycle:
    """Create and manage the parts lifecycle."""

    def __init__(
        self,
        all_parts: Dict[str, Any],
        *,
        work_dir: pathlib.Path,
        venv_dir: pathlib.Path,
    ):
        # set the cache dir for parts package management
        cache_dir = BaseDirectory.save_cache_path("charmcraft")

        try:
            self._lcm = LifecycleManager(
                {"parts": all_parts},
                application_name="charmcraft",
                work_dir=work_dir,
                cache_dir=cache_dir,
                venv_dir=venv_dir,
            )
            self._lcm.refresh_packages_list()
        except PartsError as err:
            raise CommandError(err)

    @property
    def prime_dir(self) -> pathlib.Path:
        """Return the parts prime directory path."""
        return self._lcm.project_info.prime_dir

    def run(self, target_step: Step) -> None:
        """Run the parts lifecycle.

        :param target_step: The final step to execute.
        """
        try:
            actions = self._lcm.plan(target_step)
            with self._lcm.action_executor() as aex:
                aex.execute(actions)
        except PartsError as err:
            raise CommandError(err)
