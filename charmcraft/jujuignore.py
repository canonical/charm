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

"""Indicate which files are ignored by Juju."""

import logging
import re
import typing

logger = logging.getLogger(__name__)

KEEP = "keep"
SKIP = "skip"
FORCEKEEP = "forcekeep"

_unescapes = {
    r"\!": "!",
    r"\ ": " ",
    r"\#": "#",
}


def _rstrip_unescaped(rule):
    """Remove trailing whitespace that isn't escaped."""
    i = len(rule) - 1
    last = len(rule)
    while i >= 0:
        if rule[i] == "\n" or rule[i] == "\r":
            last = i
        elif rule[i] != " ":
            break
        elif i == 0 or rule[i - 1] != "\\":
            last = i
        i -= 1
    rule = rule[:last]
    return rule


def _unescape_rule(rule):
    """Take out escape characters and trailing unescaped whitespace from the rule."""
    rule = rule.lstrip()
    rule = _rstrip_unescaped(rule)
    for old, new in _unescapes.items():
        rule = rule.replace(old, new)
    return rule


def _rule_to_regex(rule):
    """Turn a rule into a regex that we can use.

    This assumes that all the meta processing, like 'ends with /' and 'starts with !' have
    already been checked.
    """
    # Things we currently care about:
    # * = matches only within a directory "[^/]*"
    # ** = matches across directories ".*"
    # ? = matches a single character
    # [0-9] can match anything 0-9
    # This is taken from fnmatch.fnmatch, but that doesn't handle '**' and '*' also matches
    # directories

    i, n = 0, len(rule)
    res = ""
    while i < n:
        c = rule[i]
        i += 1
        if c == "*":
            if i < n and rule[i] == "*":
                i += 1
                res += ".*"
            else:
                res += "[^/]*"
        elif c == "?":
            res += "[^/]"
        elif c == "[":
            j = i
            if j < n and rule[j] == "!":
                j += 1
            if j < n and rule[j] == "]":
                j += 1
            while j < n and rule[j] != "]":
                j += 1
            if j >= n:
                res += "\\["
            else:
                stuff = rule[i:j]
                # Escape regex set operations (&~|).
                stuff = re.sub(r"([&~|])", r"\\\1", stuff)
                i = j + 1
                if stuff[0] == "!":
                    stuff = "^" + stuff[1:]
                elif stuff[0] in ("["):
                    stuff = "\\" + stuff
                res = "%s[%s]" % (res, stuff)
        elif c == "/":
            # Special case of '/**/' which can match a single '/'
            if i < n and rule[i] == "*" and rule[i - 1 : i + 3] == "/**/":
                i += 3
                res = res + ".*/"
            else:
                res = res + "/"
        else:
            res += re.escape(c)
    res += r"\Z"
    return res


class _Matcher:
    """Couple a regex with other metadata for how we should match a given pattern."""

    def __init__(
        self,
        line_num: int,
        orig_rule: str,
        invert: bool,
        only_dirs: bool,
        regex: typing.Pattern,
    ):
        self.line_num = line_num
        self.orig_rule = orig_rule
        self.invert = invert
        self.only_dirs = only_dirs
        self.compiled = re.compile(regex, re.DOTALL)

    def match(self, path: str, is_dir: bool) -> str:
        """Check if a path matches.

        Returns:
            Can return one of KEEP, SKIP, FORCEKEEP
        """
        if self.only_dirs and not is_dir:
            return KEEP
        if self.compiled.match(path):
            if self.invert:
                return FORCEKEEP
            return SKIP
        return KEEP


class JujuIgnore:
    """Track a set of ignore patterns from a .jujuignore file."""

    def __init__(self, patterns: typing.Iterable[str]):
        self._matchers = []
        self._compile_from(patterns)

    def extend_patterns(self, patterns: typing.Iterable[str]) -> None:
        """Add more patterns to the ignore list."""
        self._compile_from(patterns)

    def _compile_from(self, patterns: typing.Iterable[str]):
        for line_num, rule in enumerate(patterns, 1):
            orig_rule = rule
            rule = rule.lstrip().rstrip("\r\n")
            if not rule or rule.startswith("#"):
                continue
            invert = False
            if rule.startswith("!"):
                invert = True
                rule = rule.lstrip("!")
            rule = _unescape_rule(rule)
            only_dirs = False
            if rule.endswith("/"):
                only_dirs = True
                rule = rule.rstrip("/")
            if not rule.startswith("/"):
                # A rule that doesn't start with '/' means to match any
                # subdirectory
                rule = "**/" + rule
            regex = _rule_to_regex(rule)
            m = _Matcher(
                line_num=line_num,
                orig_rule=orig_rule,
                invert=invert,
                only_dirs=only_dirs,
                regex=regex,
            )
            self._matchers.append(m)
            logger.debug('Translated .jujuignore %d "%s" => "%s"', line_num, orig_rule, regex)

    def match(self, path: str, is_dir: bool) -> bool:
        """Check if the given path should be ignored.

        Args:
            path: A local path (eg /foo/bar or foo/bar) from the root directory of the project.
            is_dir: Indicate whether the given path is a directory (because of special handling
            from ignore files when the path ends with a '/')
        Return:
            A boolean indicating whether the ignore rules matched the given path (thus the path
            should be ignored).
        """
        if not path.startswith("/"):
            path = "/" + path
        keep = True
        for matcher in self._matchers:
            matchRes = matcher.match(path, is_dir)
            if matchRes == SKIP:
                keep = False
            elif matchRes == FORCEKEEP:
                keep = True
                break
        return not keep


# default_juju_ignore is the initial set of ignores.
# juju itself always includes these before adding the contents of .jujuignore
# NOTE that this diverges from Juju ignore list, which also ignores "version",
# because we need the version file to populate the store
default_juju_ignore = """
.git
.svn
.hg
.bzr
.tox

/build/
/revision

.jujuignore
""".split(
    "\n"
)
