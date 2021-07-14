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

import pydantic
import pytest

from craft_parts import plugins

from charmcraft import parts


def setup_module():
    plugins.register({"charm": parts.CharmPlugin})


def teardown_module():
    plugins.unregister_all()


class TestPartValidation:
    """Part data validation scenarios."""

    def test_part_validation_happy(self):
        data = {
            "plugin": "charm",
            "charm-requirements": ["stuff"],
            "source": ".",
        }
        parts.validate_part(data)

    def test_part_validation_no_plugin(self):
        data = {
            "source": ".",
        }
        with pytest.raises(ValueError) as raised:
            parts.validate_part(data)
        assert str(raised.value) == "'plugin' not defined"

    def test_part_validation_bad_property(self):
        data = {
            "plugin": "charm",
            "source": ".",
            "color": "purple",
        }
        with pytest.raises(pydantic.ValidationError) as raised:
            parts.validate_part(data)
        err = raised.value.errors()
        assert len(err) == 1
        assert err[0]["loc"] == ("color",)
        assert err[0]["msg"] == "extra fields not permitted"

    def test_part_validation_bad_type(self):
        data = {
            "plugin": "charm",
            "source": ["."],
        }
        with pytest.raises(pydantic.ValidationError) as raised:
            parts.validate_part(data)
        err = raised.value.errors()
        assert len(err) == 1
        assert err[0]["loc"] == ("source",)
        assert err[0]["msg"] == "str type expected"

    def test_part_validation_bad_plugin_property(self):
        data = {
            "plugin": "charm",
            "charm-timeout": "never",
            "source": ".",
        }
        with pytest.raises(pydantic.ValidationError) as raised:
            parts.validate_part(data)
        err = raised.value.errors()
        assert len(err) == 1
        assert err[0]["loc"] == ("charm-timeout",)
        assert err[0]["msg"] == "extra fields not permitted"

    def test_part_validation_bad_plugin_type(self):
        data = {
            "plugin": "charm",
            "charm-requirements": ".",
            "source": ".",
        }
        with pytest.raises(pydantic.ValidationError) as raised:
            parts.validate_part(data)
        err = raised.value.errors()
        assert len(err) == 1
        assert err[0]["loc"] == ("charm-requirements",)
        assert err[0]["msg"] == "value is not a valid list"
