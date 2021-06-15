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

"""Infrastructure for the 'pack' command."""

import logging
import zipfile
from argparse import Namespace

from charmcraft.cmdbase import BaseCommand, CommandError
from charmcraft.commands import build
from charmcraft.manifest import create_manifest
from charmcraft.utils import (
    SingleOptionEnsurer,
    load_yaml,
    useful_filepath,
)

logger = logging.getLogger(__name__)

# the minimum set of files in a bundle
MANDATORY_FILES = {"bundle.yaml", "manifest.yaml", "README.md"}


def build_zip(zippath, basedir, fpaths):
    """Build the final file."""
    zipfh = zipfile.ZipFile(zippath, "w", zipfile.ZIP_DEFLATED)
    for fpath in fpaths:
        zipfh.write(fpath, fpath.relative_to(basedir))
    zipfh.close()


def get_paths_to_include(config):
    """Get all file/dir paths to include."""
    dirpath = config.project.dirpath
    allpaths = set()

    # all mandatory files
    for fname in MANDATORY_FILES:
        fpath = dirpath / fname
        if not fpath.exists():
            raise CommandError("Missing mandatory file: {}.".format(fpath))
        allpaths.add(fpath)

    # the extra files (relative paths)
    bundle = config.parts.get("bundle")
    if bundle is not None:
        for spec in bundle.prime:
            fpaths = sorted(fpath for fpath in dirpath.glob(spec) if fpath.is_file())
            logger.debug("Including per prime config %r: %s.", spec, fpaths)
            allpaths.update(fpaths)

    return sorted(allpaths)


_overview = """
Build and pack a charm operator package or a bundle.

You can `juju deploy` the resulting `.charm` or bundle's `.zip`
file directly, or upload it to Charmhub with `charmcraft upload`.

For the charm you must be inside a charm directory with a valid
`metadata.yaml`, `requirements.txt` including the `ops` package
for the Python operator framework, and an operator entrypoint,
usually `src/charm.py`.  See `charmcraft init` to create a
template charm directory structure.

For the bundle you must already have a `bundle.yaml` (can be
generated by Juju) and a README.md file.
"""


class PackCommand(BaseCommand):
    """Build the bundle or the charm.

    If charmcraft.yaml missing or its 'type' key indicates a charm,
    use the "build" infrastructure to create the charm.

    Otherwise pack the bundle.
    """

    name = "pack"
    help_msg = "Build the charm or bundle"
    overview = _overview
    needs_config = False  # optional until we fully support charms here

    def fill_parser(self, parser):
        """Add own parameters to the general parser."""
        parser.add_argument(
            "-e",
            "--entrypoint",
            type=SingleOptionEnsurer(useful_filepath),
            help=(
                "The executable which is the operator entry point; defaults to 'src/charm.py'"
            ),
        )
        parser.add_argument(
            "-r",
            "--requirement",
            action="append",
            type=useful_filepath,
            help=(
                "File(s) listing needed PyPI dependencies (can be used multiple "
                "times); defaults to 'requirements.txt'"
            ),
        )

    def run(self, parsed_args):
        """Run the command."""
        # decide if this will work on a charm or a bundle
        if self.config.type == "charm" or not self.config.project.config_provided:
            self._pack_charm(parsed_args)
        else:
            if parsed_args.entrypoint is not None:
                raise CommandError(
                    "The -e/--entry option is valid only when packing a charm"
                )
            if parsed_args.requirement is not None:
                raise CommandError(
                    "The -r/--requirement option is valid only when packing a charm"
                )
            self._pack_bundle()

    def _pack_charm(self, parsed_args):
        """Pack a charm."""
        # adapt arguments to use the build infrastructure
        parsed_args = Namespace(
            **{
                "from": self.config.project.dirpath,
                "entrypoint": parsed_args.entrypoint,
                "requirement": parsed_args.requirement,
            }
        )

        # mimic the "build" command
        validator = build.Validator()
        args = validator.process(parsed_args)
        logger.debug("working arguments: %s", args)
        builder = build.Builder(args, self.config)
        builder.run()

    def _pack_bundle(self):
        """Pack a bundle."""
        # get the config files
        bundle_filepath = self.config.project.dirpath / "bundle.yaml"
        bundle_config = load_yaml(bundle_filepath)
        if bundle_config is None:
            raise CommandError(
                "Missing or invalid main bundle file: '{}'.".format(bundle_filepath)
            )
        bundle_name = bundle_config.get("name")
        if not bundle_name:
            raise CommandError(
                "Invalid bundle config; missing a 'name' field indicating the bundle's name in "
                "file '{}'.".format(bundle_filepath)
            )

        # so far 'pack' works for bundles only (later this will operate also on charms)
        if self.config.type != "bundle":
            raise CommandError(
                "Bad config: 'type' field in charmcraft.yaml must be 'bundle' for this command."
            )

        # pack everything
        project = self.config.project
        manifest_filepath = create_manifest(
            project.dirpath, project.started_at, build.DEFAULT_BASES_CONFIGURATION
        )
        try:
            paths = get_paths_to_include(self.config)
            zipname = project.dirpath / (bundle_name + ".zip")
            build_zip(zipname, project.dirpath, paths)
        finally:
            manifest_filepath.unlink()
        logger.info("Created '%s'.", zipname)
