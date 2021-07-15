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

"""Infrastructure for the 'build' command."""

import errno
import logging
import os
import pathlib
import shutil
import subprocess
import zipfile
from typing import List, Optional

from charmcraft import linters
from charmcraft.bases import check_if_base_matches_host
from charmcraft.cmdbase import BaseCommand, CommandError
from charmcraft.config import Base, BasesConfiguration, Config
from charmcraft.deprecations import notify_deprecation
from charmcraft.env import (
    get_managed_environment_home_path,
    get_managed_environment_project_path,
    is_charmcraft_running_in_managed_mode,
)
from charmcraft.jujuignore import JujuIgnore, default_juju_ignore
from charmcraft.logsetup import message_handler
from charmcraft.manifest import create_manifest
from charmcraft.metadata import parse_metadata_yaml
from charmcraft.providers import (
    capture_logs_from_instance,
    ensure_provider_is_available,
    is_base_providable,
    launched_environment,
)
from charmcraft.utils import make_executable

logger = logging.getLogger(__name__)

# Some constants that are used through the code.
BUILD_DIRNAME = "build"
VENV_DIRNAME = "venv"

# The file name and template for the dispatch script
DISPATCH_FILENAME = "dispatch"
# If Juju doesn't support the dispatch mechanism, it will execute the
# hook, and we'd need sys.argv[0] to be the name of the hook but it's
# geting lost by calling this dispatch, so we fake JUJU_DISPATCH_PATH
# to be the value it would've otherwise been.
DISPATCH_CONTENT = """#!/bin/sh

JUJU_DISPATCH_PATH="${{JUJU_DISPATCH_PATH:-$0}}" PYTHONPATH=lib:venv ./{entrypoint_relative_path}
"""

# The minimum set of hooks to be provided for compatibility with old Juju
MANDATORY_HOOK_NAMES = {"install", "start", "upgrade-charm"}
HOOKS_DIR = "hooks"


def _format_run_on_base(base: Base) -> str:
    """Formulate charm string for base section."""
    return "-".join([base.name, base.channel, *base.architectures])


def _format_bases_config(bases_config: BasesConfiguration) -> str:
    """Formulate charm string for bases configuration section."""
    return "_".join([_format_run_on_base(r) for r in bases_config.run_on])


def format_charm_file_name(
    charm_name: str, bases_config: Optional[BasesConfiguration] = None
) -> str:
    """Formulate charm file name.

    :param charm_name: Name of charm.
    :param bases_config: Bases configuration for charm.  None will use legacy
        format that will be removed shortly.

    :returns: File name string, including .charm extension.
    """
    # TODO: Patterson 2021-06-14 Temporary legacy support prior to bases configuration.
    if bases_config is None:
        return charm_name + ".charm"

    return "_".join([charm_name, _format_bases_config(bases_config)]) + ".charm"


def _pip_needs_system():
    """Determine whether pip3 defaults to --user, needing --system to turn it off."""
    cmd = [
        "python3",
        "-c",
        (
            "from pip.commands.install import InstallCommand; "
            'assert InstallCommand().cmd_opts.get_option("--system") is not None'
        ),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def polite_exec(cmd):
    """Execute a command, only showing output if error."""
    logger.debug("Running external command %s", cmd)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    except Exception as err:
        logger.error("Executing %s crashed with %r", cmd, err)
        return 1

    for line in proc.stdout:
        logger.debug(":: %s", line.rstrip())
    retcode = proc.wait()

    if retcode:
        logger.error("Executing %s failed with return code %d", cmd, retcode)
    return retcode


def relativise(src, dst):
    """Build a relative path from src to dst."""
    return pathlib.Path(os.path.relpath(str(dst), str(src.parent)))


class Builder:
    """The package builder."""

    def __init__(self, args, config):
        self.charmdir = args["from"]
        self.entrypoint = args["entrypoint"]
        self.requirement_paths = args["requirement"]
        self.force_packing = args["force"]

        self.buildpath = self.charmdir / BUILD_DIRNAME
        self.ignore_rules = self._load_juju_ignore()
        self.config = config
        self.metadata = parse_metadata_yaml(self.charmdir)

    def show_linting_results(self, linting_results):
        """Manage the linters results, show some in different conditions, decide if continue."""
        attribute_results = []
        lint_results_by_outcome = {}
        for result in linting_results:
            if result.result == linters.IGNORED:
                continue
            if result.check_type == linters.CheckType.attribute:
                attribute_results.append(result)
            else:
                lint_results_by_outcome.setdefault(result.result, []).append(result)

        # show attribute results
        for result in attribute_results:
            logger.debug(
                "Check result: %s [%s] %s (%s; see more at %s).",
                result.name,
                result.check_type,
                result.result,
                result.text,
                result.url,
            )

        # show warnings (if any), then errors (if any)
        template = "- %s: %s (%s)"
        if linters.WARNINGS in lint_results_by_outcome:
            logger.info("Lint Warnings:")
            for result in lint_results_by_outcome[linters.WARNINGS]:
                logger.info(template, result.name, result.text, result.url)
        if linters.ERRORS in lint_results_by_outcome:
            logger.info("Lint Errors:")
            for result in lint_results_by_outcome[linters.ERRORS]:
                logger.info(template, result.name, result.text, result.url)
            if self.force_packing:
                logger.info("Packing anyway as requested.")
            else:
                raise CommandError(
                    "Exiting after lint errors (use --force to pack anyway).", retcode=2
                )

    def build_charm(self, bases_config: BasesConfiguration) -> str:
        """Build the charm.

        :param bases_config: Bases configuration to use for build.

        :returns: File name of charm.
        """
        logger.debug("Building charm in %r", str(self.buildpath))

        if self.buildpath.exists():
            shutil.rmtree(str(self.buildpath))
        self.buildpath.mkdir()

        linked_entrypoint = self.handle_generic_paths()
        self.handle_dispatcher(linked_entrypoint)
        self.handle_dependencies()

        # run linters and show the results
        linting_results = linters.analyze(self.config, self.buildpath)
        self.show_linting_results(linting_results)

        create_manifest(
            self.buildpath,
            self.config.project.started_at,
            bases_config,
            linting_results,
        )

        zipname = self.handle_package(bases_config)
        logger.info("Created '%s'.", zipname)
        return zipname

    def run(
        self, bases_indices: Optional[List[int]] = None, destructive_mode: bool = False
    ) -> List[str]:
        """Run build process.

        In managed-mode or destructive-mode, build for each bases configuration
        which has a matching build-on to the host we are executing on.  Warn for
        each base configuration that is incompatible.  Error if unable to
        produce any builds for any bases configuration.

        :returns: List of charm files created.
        """
        charms: List[str] = []

        managed_mode = is_charmcraft_running_in_managed_mode()
        if not managed_mode and not destructive_mode:
            ensure_provider_is_available()

        if not (self.charmdir / "charmcraft.yaml").exists():
            notify_deprecation("dn02")

        for bases_index, bases_config in enumerate(self.config.bases):
            if bases_indices and bases_index not in bases_indices:
                logger.debug(
                    "Skipping 'bases[%d]' due to --base-index usage.",
                    bases_index,
                )
                continue

            for build_on_index, build_on in enumerate(bases_config.build_on):
                if managed_mode or destructive_mode:
                    matches, reason = check_if_base_matches_host(build_on)
                else:
                    matches, reason = is_base_providable(build_on)

                if matches:
                    logger.debug(
                        "Building for 'bases[%d]' as host matches 'build-on[%d]'.",
                        bases_index,
                        build_on_index,
                    )
                    if managed_mode or destructive_mode:
                        charm_name = self.build_charm(bases_config)
                    else:
                        charm_name = self.pack_charm_in_instance(
                            bases_index=bases_index,
                            build_on=build_on,
                            build_on_index=build_on_index,
                        )

                    charms.append(charm_name)
                    break
                else:
                    logger.info(
                        "Skipping 'bases[%d].build-on[%d]': %s.",
                        bases_index,
                        build_on_index,
                        reason,
                    )
            else:
                logger.warning(
                    "No suitable 'build-on' environment found in 'bases[%d]' configuration.",
                    bases_index,
                )

        if not charms:
            raise CommandError(
                "No suitable 'build-on' environment found in any 'bases' configuration."
            )

        return charms

    def pack_charm_in_instance(
        self, *, bases_index: int, build_on: Base, build_on_index: int
    ) -> str:
        """Pack instance in Charm."""
        charm_name = format_charm_file_name(
            self.metadata.name, self.config.bases[bases_index]
        )

        # If building in project directory, use the project path as the working
        # directory. The output charms will be placed in the correct directory
        # without needing retrieval. If outputing to a directory other than the
        # charm project directory, we need to output the charm outside the
        # project directory and can retrieve it when complete.
        cwd = pathlib.Path.cwd()
        if cwd == self.charmdir:
            instance_output_dir = get_managed_environment_project_path()
            pull_charm = False
        else:
            instance_output_dir = get_managed_environment_home_path()
            pull_charm = True

        cmd = ["charmcraft", "pack", "--bases-index", str(bases_index)]

        if message_handler.mode == message_handler.VERBOSE:
            cmd.append("--verbose")
        elif message_handler.mode == message_handler.QUIET:
            cmd.append("--quiet")

        logger.info(f"Packing charm {charm_name!r}...")
        with launched_environment(
            charm_name=self.metadata.name,
            project_path=self.charmdir,
            base=build_on,
            bases_index=bases_index,
            build_on_index=build_on_index,
        ) as instance:
            try:
                instance.execute_run(
                    cmd,
                    check=True,
                    cwd=instance_output_dir.as_posix(),
                )
            except subprocess.CalledProcessError as error:
                capture_logs_from_instance(instance)
                raise CommandError(
                    f"Failed to build charm for bases index '{bases_index}'."
                ) from error

            if pull_charm:
                try:
                    instance.pull_file(
                        source=instance_output_dir / charm_name,
                        destination=cwd / charm_name,
                    )
                except FileNotFoundError as error:
                    raise CommandError(
                        "Unexpected error retrieving charm from instance."
                    ) from error

        return charm_name

    def _load_juju_ignore(self):
        ignore = JujuIgnore(default_juju_ignore)
        path = self.charmdir / ".jujuignore"
        if path.exists():
            with path.open("r", encoding="utf-8") as ignores:
                ignore.extend_patterns(ignores)
        return ignore

    def create_symlink(self, src_path, dest_path):
        """Create a symlink in dest_path pointing relatively like src_path.

        It also verifies that the linked dir or file is inside the project.
        """
        resolved_path = src_path.resolve()
        if self.charmdir in resolved_path.parents:
            relative_link = relativise(src_path, resolved_path)
            dest_path.symlink_to(relative_link)
        else:
            rel_path = src_path.relative_to(self.charmdir)
            logger.warning(
                "Ignoring symlink because targets outside the project: %r",
                str(rel_path),
            )

    def handle_generic_paths(self):
        """Handle all files and dirs except what's ignored and what will be handled later.

        Works differently for the different file types:
        - regular files: hard links
        - directories: created
        - symlinks: respected if are internal to the project
        - other types (blocks, mount points, etc): ignored
        """
        logger.debug("Linking in generic paths")

        for basedir, dirnames, filenames in os.walk(
            str(self.charmdir), followlinks=False
        ):
            abs_basedir = pathlib.Path(basedir)
            rel_basedir = abs_basedir.relative_to(self.charmdir)

            # process the directories
            ignored = []
            for pos, name in enumerate(dirnames):
                rel_path = rel_basedir / name
                abs_path = abs_basedir / name

                if self.ignore_rules.match(str(rel_path), is_dir=True):
                    logger.debug(
                        "Ignoring directory because of rules: %r", str(rel_path)
                    )
                    ignored.append(pos)
                elif abs_path.is_symlink():
                    dest_path = self.buildpath / rel_path
                    self.create_symlink(abs_path, dest_path)
                else:
                    dest_path = self.buildpath / rel_path
                    dest_path.mkdir(mode=abs_path.stat().st_mode)

            # in the future don't go inside ignored directories
            for pos in reversed(ignored):
                del dirnames[pos]

            # process the files
            for name in filenames:
                rel_path = rel_basedir / name
                abs_path = abs_basedir / name

                if self.ignore_rules.match(str(rel_path), is_dir=False):
                    logger.debug("Ignoring file because of rules: %r", str(rel_path))
                elif abs_path.is_symlink():
                    dest_path = self.buildpath / rel_path
                    self.create_symlink(abs_path, dest_path)
                elif abs_path.is_file():
                    dest_path = self.buildpath / rel_path
                    try:
                        os.link(str(abs_path), str(dest_path))
                    except PermissionError:
                        # when not allowed to create hard links
                        shutil.copy2(str(abs_path), str(dest_path))
                    except OSError as e:
                        if e.errno != errno.EXDEV:
                            raise
                        shutil.copy2(str(abs_path), str(dest_path))
                else:
                    logger.debug("Ignoring file because of type: %r", str(rel_path))

        # the linked entrypoint is calculated here because it's when it's really in the build dir
        linked_entrypoint = self.buildpath / self.entrypoint.relative_to(self.charmdir)
        return linked_entrypoint

    def handle_dispatcher(self, linked_entrypoint):
        """Handle modern and classic dispatch mechanisms."""
        # dispatch mechanism, create one if wasn't provided by the project
        dispatch_path = self.buildpath / DISPATCH_FILENAME
        if not dispatch_path.exists():
            logger.debug("Creating the dispatch mechanism")
            dispatch_content = DISPATCH_CONTENT.format(
                entrypoint_relative_path=linked_entrypoint.relative_to(self.buildpath)
            )
            with dispatch_path.open("wt", encoding="utf8") as fh:
                fh.write(dispatch_content)
                make_executable(fh)

        # bunch of symlinks, to support old juju: verify that any of the already included hooks
        # in the directory is not linking directly to the entrypoint, and also check all the
        # mandatory ones are present
        dest_hookpath = self.buildpath / HOOKS_DIR
        if not dest_hookpath.exists():
            dest_hookpath.mkdir()

        # get those built hooks that we need to replace because they are pointing to the
        # entrypoint directly and we need to fix the environment in the middle
        current_hooks_to_replace = []
        for node in dest_hookpath.iterdir():
            if node.resolve() == linked_entrypoint:
                current_hooks_to_replace.append(node)
                node.unlink()
                logger.debug(
                    "Replacing existing hook %r as it's a symlink to the entrypoint",
                    node.name,
                )

        # include the mandatory ones and those we need to replace
        hooknames = MANDATORY_HOOK_NAMES | {x.name for x in current_hooks_to_replace}
        for hookname in hooknames:
            logger.debug("Creating the %r hook script pointing to dispatch", hookname)
            dest_hook = dest_hookpath / hookname
            if not dest_hook.exists():
                relative_link = relativise(dest_hook, dispatch_path)
                dest_hook.symlink_to(relative_link)

    def handle_dependencies(self):
        """Handle from-directory and virtualenv dependencies."""
        logger.debug("Installing dependencies")

        # virtualenv with other dependencies (if any)
        if self.requirement_paths:
            retcode = polite_exec(["pip3", "list"])
            if retcode:
                raise CommandError("problems using pip")

            venvpath = self.buildpath / VENV_DIRNAME
            cmd = [
                "pip3",
                "install",  # base command
                "--target={}".format(
                    venvpath
                ),  # put all the resulting files in that specific dir
            ]
            if _pip_needs_system():
                logger.debug("adding --system to work around pip3 defaulting to --user")
                cmd.append("--system")
            for reqspath in self.requirement_paths:
                cmd.append(
                    "--requirement={}".format(reqspath)
                )  # the dependencies file(s)
            retcode = polite_exec(cmd)
            if retcode:
                raise CommandError("problems installing dependencies")

    def handle_package(self, bases_config: Optional[BasesConfiguration] = None):
        """Handle the final package creation."""
        logger.debug("Creating the package itself")
        zipname = format_charm_file_name(self.metadata.name, bases_config)
        zipfh = zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED)
        for dirpath, dirnames, filenames in os.walk(self.buildpath, followlinks=True):
            dirpath = pathlib.Path(dirpath)
            for filename in filenames:
                filepath = dirpath / filename
                zipfh.write(str(filepath), str(filepath.relative_to(self.buildpath)))

        zipfh.close()
        return zipname


class Validator:
    """A validator of all received options."""

    _options = [
        "from",  # this needs to be processed first, as it's a base dir to find other files
        "destructive_mode",
        "entrypoint",
        "requirement",
        "bases_indices",
        "force",
    ]

    def __init__(self, config: Config):
        self.basedir = None  # this will be fulfilled when processing 'from'
        self.config = config

    def process(self, parsed_args):
        """Process the received options."""
        result = {}
        for opt in self._options:
            meth = getattr(self, "validate_" + opt)
            result[opt] = meth(getattr(parsed_args, opt, None))
        return result

    def validate_bases_indices(self, bases_indices):
        """Validate that bases index is valid."""
        if not bases_indices:
            return

        for bases_index in bases_indices:
            if bases_index < 0:
                raise CommandError(
                    f"Bases index '{bases_index}' is invalid (must be >= 0)."
                )

            if not self.config.bases:
                raise CommandError(
                    "No bases configuration found, required when using --bases-index.",
                )

            if bases_index >= len(self.config.bases):
                raise CommandError(
                    f"No bases configuration found for specified index '{bases_index}'."
                )

    def validate_destructive_mode(self, destructive_mode):
        """Validate that destructive mode option is valid."""
        if not isinstance(destructive_mode, bool):
            return False

        return destructive_mode

    def validate_from(self, dirpath):
        """Validate that the charm dir is there and yes, a directory."""
        if dirpath is None:
            dirpath = pathlib.Path.cwd()
        else:
            dirpath = dirpath.expanduser().absolute()

        if not dirpath.exists():
            raise CommandError(
                "Charm directory was not found: {!r}".format(str(dirpath))
            )
        if not dirpath.is_dir():
            raise CommandError(
                "Charm directory is not really a directory: {!r}".format(str(dirpath))
            )

        self.basedir = dirpath
        return dirpath

    def validate_entrypoint(self, filepath):
        """Validate that the entrypoint exists and is executable."""
        if filepath is None:
            filepath = self.basedir / "src" / "charm.py"
        else:
            filepath = filepath.expanduser().absolute()

        if not filepath.exists():
            raise CommandError(
                "Charm entry point was not found: {!r}".format(str(filepath))
            )
        if self.basedir not in filepath.parents:
            raise CommandError(
                "Charm entry point must be inside the project: {!r}".format(
                    str(filepath)
                )
            )
        if not os.access(filepath, os.X_OK):
            raise CommandError(
                "Charm entry point must be executable: {!r}".format(str(filepath))
            )
        return filepath

    def validate_requirement(self, filepaths):
        """Validate that the given requirement(s) (if any) exist.

        If not specified, default to requirements.txt if there.
        """
        if filepaths is None:
            req = self.basedir / "requirements.txt"
            if req.exists() and os.access(req, os.R_OK):
                return [req]
            return []

        filepaths = [x.expanduser().absolute() for x in filepaths]
        for fpath in filepaths:
            if not fpath.exists():
                raise CommandError(
                    "the requirements file was not found: {!r}".format(str(fpath))
                )
        return filepaths

    def validate_force(self, value):
        """Validate the value (just convert to bool to make None explicit)."""
        return bool(value)


_overview = """
Build a charm operator package.

You can `juju deploy` the resulting `.charm` file directly, or upload it
to Charmhub with `charmcraft upload`.

You must be inside a charm directory with a valid `metadata.yaml`,
`requirements.txt` including the `ops` package for the Python operator
framework, and an operator entrypoint, usually `src/charm.py`.

See `charmcraft init` to create a template charm directory structure.
"""


class BuildCommand(BaseCommand):
    """Build the charm."""

    name = "build"
    help_msg = "Build the charm"
    overview = _overview
    common = True

    def fill_parser(self, parser):
        """Add own parameters to the general parser."""
        parser.add_argument(
            "-f",
            "--from",
            type=pathlib.Path,
            help="Charm directory with metadata.yaml where the build "
            "takes place; defaults to '.'",
        )
        parser.add_argument(
            "-e",
            "--entrypoint",
            type=pathlib.Path,
            help="The executable which is the operator entry point; "
            "defaults to 'src/charm.py'",
        )
        parser.add_argument(
            "-r",
            "--requirement",
            action="append",
            type=pathlib.Path,
            help="File(s) listing needed PyPI dependencies (can be used multiple "
            "times); defaults to 'requirements.txt'",
        )

    def run(self, parsed_args):
        """Run the command."""
        validator = Validator(self.config)
        args = validator.process(parsed_args)
        logger.debug("working arguments: %s", args)
        builder = Builder(args, self.config)
        builder.run(destructive_mode=args["destructive_mode"])
