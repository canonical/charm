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

"""Logic related to metadata.yaml."""

import logging
import pathlib
from typing import Any, Dict

import pydantic
import yaml

from charmcraft.cmdbase import CommandError
from charmcraft.config import format_pydantic_errors

logger = logging.getLogger(__name__)

CHARM_METADATA = "metadata.yaml"


class CharmMetadata(pydantic.BaseModel, frozen=True, validate_all=True):
    """Object representing metadata.yaml contents."""

    name: pydantic.StrictStr

    @classmethod
    def unmarshal(cls, obj: Dict[str, Any]):
        """Unmarshal object with necessary translations and error handling.

        :returns: valid CharmMetadata.

        :raises CommandError: On failure to unmarshal object.
        """
        try:
            return cls.parse_obj(obj)
        except pydantic.error_wrappers.ValidationError as error:
            raise CommandError(format_pydantic_errors(error.errors(), file_name=CHARM_METADATA))


def parse_metadata_yaml(charm_dir: pathlib.Path) -> Dict[str, Any]:
    """Parse project's metadata.yaml.

    :returns: Metadata dictionary object, if it exists.
    """
    metadata_path = charm_dir / CHARM_METADATA
    logger.debug("Parsing %r", str(metadata_path))

    if not metadata_path.exists():
        raise CommandError("Missing mandatory metadata.yaml.")

    with metadata_path.open("rt", encoding="utf8") as fh:
        metadata = yaml.safe_load(fh)
        return CharmMetadata.unmarshal(metadata)
