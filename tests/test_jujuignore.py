# Copyright 2020 Canonical Ltd.
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

import io
import pathlib
import subprocess
import textwrap
import tempfile

from charmcraft import jujuignore


def test_default_important_files():
    """Don't ignore important files by default."""
    ignore = jujuignore.JujuIgnore(jujuignore.default_juju_ignore)
    assert not ignore.match("version", is_dir=False)


def test_jujuignore_only_dir():
    ignore = jujuignore.JujuIgnore(["target/"])
    assert ignore.match("target", is_dir=True)
    assert ignore.match("foo/target", is_dir=True)
    assert not ignore.match("foo/1target", is_dir=True)
    assert not ignore.match("foo/target", is_dir=False)


def test_jujuignore_any_target():
    ignore = jujuignore.JujuIgnore(["target"])
    assert ignore.match("target", is_dir=True)
    assert ignore.match("/foo/target", is_dir=True)
    assert not ignore.match("/foo/1target", is_dir=True)
    assert ignore.match("/foo/target", is_dir=False)


def test_jujuignore_only_root_target_dir():
    ignore = jujuignore.JujuIgnore(["/target/"])
    assert ignore.match("/target", is_dir=True)
    assert not ignore.match("/foo/target", is_dir=True)
    assert not ignore.match("/foo/1target", is_dir=True)
    assert not ignore.match("/foo/target", is_dir=False)
    assert not ignore.match("/target", is_dir=False)


def test_jujuignore_only_root_target_file_or_dir():
    ignore = jujuignore.JujuIgnore(["/target"])
    assert ignore.match("/target", is_dir=True)
    assert not ignore.match("/foo/target", is_dir=True)
    assert not ignore.match("/foo/1target", is_dir=True)
    assert not ignore.match("/foo/target", is_dir=False)
    assert ignore.match("/target", is_dir=False)


def test_jujuignore_all_py_files():
    ignore = jujuignore.JujuIgnore(["*.py"])
    assert not ignore.match("/target", is_dir=True)
    assert ignore.match("/target.py", is_dir=True)
    assert ignore.match("/target.py", is_dir=False)
    assert ignore.match("/foo/target.py", is_dir=True)
    assert ignore.match("/foo/target.py", is_dir=False)
    assert not ignore.match("/target.pyT", is_dir=True)
    assert not ignore.match("/target.pyT", is_dir=False)


def test_jujuignore_all_py_files_in_foo():
    ignore = jujuignore.JujuIgnore(["/foo/*.py"])
    assert not ignore.match("/target.py", is_dir=True)
    assert not ignore.match("/target.py", is_dir=False)
    assert ignore.match("/foo/target.py", is_dir=True)
    assert ignore.match("/foo/target.py", is_dir=False)
    assert not ignore.match("/foo/sub/target.py", is_dir=False)


def test_jujuignore_ignore_comment():
    ignore = jujuignore.JujuIgnore(
        [
            "#comment",
            "target",
        ]
    )
    assert ignore.match("/target", is_dir=True)
    assert not ignore.match("/comment", is_dir=False)
    assert not ignore.match("/#comment", is_dir=False)
    assert not ignore.match("#comment", is_dir=False)
    assert not ignore.match("/foo/comment", is_dir=False)
    assert not ignore.match("/foo/#comment", is_dir=False)


def test_jujuignore_escaped_comment():
    ignore = jujuignore.JujuIgnore(
        [
            "\\#comment",
            "target",
        ]
    )
    assert ignore.match("/target", is_dir=True)
    assert ignore.match("/#comment", is_dir=False)
    assert ignore.match("#comment", is_dir=False)
    assert not ignore.match("/foo/comment", is_dir=False)
    assert ignore.match("/foo/#comment", is_dir=False)


def test_jujuignore_subdirectory_match():
    ignore = jujuignore.JujuIgnore(["apps/logs/"])
    assert not ignore.match("/logs", is_dir=True)
    assert not ignore.match("/apps", is_dir=True)
    assert ignore.match("/apps/logs", is_dir=True)
    assert not ignore.match("/apps/logs", is_dir=False)
    assert not ignore.match("/apps/foo/logs", is_dir=True)


def test_jujuignore_sub_subdirectory_match():
    ignore = jujuignore.JujuIgnore(["apps/*/logs/"])
    assert not ignore.match("/logs", is_dir=True)
    assert not ignore.match("/apps", is_dir=True)
    assert not ignore.match("/apps/logs", is_dir=True)
    assert not ignore.match("/apps/logs", is_dir=False)
    assert ignore.match("/apps/foo/logs", is_dir=True)
    assert ignore.match("/apps/bar/logs", is_dir=True)
    assert not ignore.match("/apps/baz/logs", is_dir=False)
    assert not ignore.match("/apps/foo/bar/logs", is_dir=True)


def test_jujuignore_any_subdirectory_match():
    ignore = jujuignore.JujuIgnore(["apps/**/logs/"])
    assert not ignore.match("/logs", is_dir=True)
    assert not ignore.match("/apps", is_dir=True)
    assert ignore.match("/apps/logs", is_dir=True)
    assert not ignore.match("/apps/logs", is_dir=False)
    assert ignore.match("/apps/foo/logs", is_dir=True)
    assert ignore.match("/apps/bar/logs", is_dir=True)
    assert ignore.match("/apps/bar/bing/logs", is_dir=True)
    assert not ignore.match("/apps/baz/logs", is_dir=False)


def test_jujuignore_everything_under_foo():
    ignore = jujuignore.JujuIgnore(["foo/**"])
    assert not ignore.match("/foo", is_dir=True)
    assert ignore.match("/foo/a", is_dir=True)
    assert ignore.match("/foo/a", is_dir=False)
    assert ignore.match("/foo/a/b", is_dir=False)


def test_jujuignore_everything_under_foo_but_readme():
    ignore = jujuignore.JujuIgnore(
        [
            "foo/**",
            "!foo/README.md",
        ]
    )
    assert not ignore.match("/foo", is_dir=True)
    assert ignore.match("/foo/a", is_dir=True)
    assert ignore.match("/foo/a", is_dir=False)
    assert ignore.match("/foo/a/b", is_dir=False)
    assert not ignore.match("/foo/README.md", is_dir=False)


def test_jujuignore_negation():
    ignore = jujuignore.JujuIgnore(
        [
            "*.py",
            "!foo.py",
            "!!!bar.py",
        ]
    )
    assert not ignore.match("bar.py", is_dir=False)
    assert not ignore.match("foo.py", is_dir=False)
    assert ignore.match("baz.py", is_dir=False)
    assert not ignore.match("foo/bar.py", is_dir=False)
    assert not ignore.match("foo/foo.py", is_dir=False)
    assert ignore.match("foo/baz.py", is_dir=False)


def test_jujuignore_multiple_doublestar():
    ignore = jujuignore.JujuIgnore(["foo/**/bar/**/baz"])
    assert ignore.match("/foo/1/2/bar/baz", is_dir=True)
    assert ignore.match("/foo/1/2/bar/1/2/baz", is_dir=True)
    assert ignore.match("/foo/bar/1/2/baz", is_dir=True)
    assert ignore.match("/foo/1/bar/baz", is_dir=True)
    assert ignore.match("/foo/bar/baz", is_dir=True)


def test_jujuignore_trim_unescaped_trailing_space():
    ignore = jujuignore.JujuIgnore(
        [
            r"foo  ",
            r"bar\ \ ",
        ]
    )
    assert ignore.match("/foo", is_dir=True)
    assert not ignore.match("/bar", is_dir=True)
    assert ignore.match("/bar  ", is_dir=True)


def test_jujuignore_escaped_bang():
    ignore = jujuignore.JujuIgnore(
        [
            r"foo",
            r"!/foo",
            r"\!foo",
        ]
    )
    assert not ignore.match("/foo", is_dir=True)
    assert ignore.match("/bar/foo", is_dir=True)
    assert ignore.match("!foo", is_dir=True)


def test_jujuignore_leading_whitespace():
    ignore = jujuignore.JujuIgnore(
        [
            r"foo",
            r" bar",
            r" #comment",
        ]
    )
    assert ignore.match("/foo", is_dir=True)
    assert ignore.match("/bar", is_dir=True)
    assert ignore.match("/bar/foo", is_dir=True)
    assert not ignore.match("#comment", is_dir=True)
    assert not ignore.match("comment", is_dir=True)


def test_jujuignore_bracket():
    ignore = jujuignore.JujuIgnore(
        [
            r"*.py[cod]",
        ]
    )
    assert not ignore.match("foo.py", is_dir=False)
    assert ignore.match("foo.pyc", is_dir=False)
    assert ignore.match("foo.pyo", is_dir=False)
    assert ignore.match("foo.pyd", is_dir=False)


def test_jujuignore_simple_match():
    ignore = jujuignore.JujuIgnore(
        [
            r"foo",
        ]
    )
    assert ignore.match("/foo", is_dir=True)
    assert ignore.match("/bar/foo", is_dir=True)
    assert not ignore.match("/bar/bfoo", is_dir=True)
    assert not ignore.match("/bfoo", is_dir=True)


def test_jujuignore_star_match():
    ignore = jujuignore.JujuIgnore(
        [
            r"foo*.py",
        ]
    )
    assert ignore.match("/foo.py", is_dir=False)
    assert ignore.match("/foo2.py", is_dir=False)
    assert ignore.match("/foobar.py", is_dir=False)
    assert ignore.match("/bar/foo.py", is_dir=False)
    assert not ignore.match("/foo/2.py", is_dir=False)


def test_jujuignore_paths_with_newlines():
    ignore = jujuignore.JujuIgnore([r"bar/**/*.py"])
    assert ignore.match("/bar/foo.py", is_dir=False)
    assert ignore.match("/bar/f\noo.py", is_dir=False)
    assert ignore.match("/bar/baz/f\noo.py", is_dir=False)
    assert ignore.match("/bar/b\nz/f\noo.py", is_dir=False)


def test_rstrip_unescaped():
    assert jujuignore._rstrip_unescaped(r"") == ""
    assert jujuignore._rstrip_unescaped(r" ") == ""
    assert jujuignore._rstrip_unescaped(r"a") == "a"
    assert jujuignore._rstrip_unescaped(r"a ") == "a"
    assert jujuignore._rstrip_unescaped(r"a  ") == "a"
    assert jujuignore._rstrip_unescaped(r"a\  ") == r"a\ "
    assert jujuignore._rstrip_unescaped(r"a foo\  ") == r"a foo\ "


def test_unescape_rule():
    assert jujuignore._unescape_rule(r"") == ""
    assert jujuignore._unescape_rule(r" ") == ""
    assert jujuignore._unescape_rule(r"\#") == "#"
    assert jujuignore._unescape_rule(r"\!") == "!"
    assert jujuignore._unescape_rule(r"\ ") == " "
    assert jujuignore._unescape_rule(r" foo\ ") == "foo "


def test_from_file():
    content = io.StringIO(
        textwrap.dedent(
            """\
    foo
    /bar
    """
        )
    )
    ignore = jujuignore.JujuIgnore(content)
    assert ignore.match("foo", is_dir=False)
    assert ignore.match("/foo", is_dir=False)
    assert ignore.match("/bar", is_dir=False)
    assert not ignore.match("/foo/bar", is_dir=False)


def assertMatchedAndNonMatched(globs, matched, unmatched, skip_git=False):
    """For a given set of globs, check that it does and doesn't match as expected"""
    ignore = jujuignore.JujuIgnore(globs)
    for m in matched:
        assert ignore.match(m, is_dir=False), "{} should have matched".format(m)
    for m in unmatched:
        assert not ignore.match(m, is_dir=False), "{} should not have matched".format(m)
    if skip_git:
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init", tmpdir], check=True)
        with open(str(pathlib.Path(tmpdir) / ".gitignore"), "wt") as gitignore:
            gitignore.writelines([g + "\n" for g in globs])
        input = "".join([m.lstrip("/") + "\n" for m in matched + unmatched])
        check = True
        if len(matched) == 0:
            # We don't check git return value because it returns nonzero if no paths match
            check = False
        p = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            check=check,
            input=input,
            stdout=subprocess.PIPE,
            cwd=tmpdir,
            universal_newlines=True,
        )
    matched_out = p.stdout.splitlines()
    assert sorted(matched) == sorted(matched_out), "expected exactly {} to match not {}".format(
        matched, matched_out
    )


def test_star_vs_star_start():
    assertMatchedAndNonMatched(
        ["/*.py", "**/foo"],
        # Only top level .py files, but foo at any level
        ["a.py", "b.py", "foo", "bar/foo"],
        ["bar/b.py"],
        # 'foo/a.py',  git matches foo/a.py because of foo, ours doesn't but I don't think it
        # matters because the whole directory would have already been skipped
    )


def test_questionmark():
    assertMatchedAndNonMatched(
        ["foo?.py"],
        ["fooa.py", "foob.py"],
        ["foo.py", "footwo.py", "foo/.py"],
    )


def test_brackets():
    assertMatchedAndNonMatched(
        ["*.py[cod]"],
        ["a.pyc", "b.pyo", "d.pyd", "foo/.pyc", "bar/__pycache__.pyc"],
        ["a.py", "b.pyq", "c.so", "foo/__pycache__/bar.py"],
    )


def test_bracket_ranges():
    assertMatchedAndNonMatched(
        ["foo[1-9].py"],
        ["foo1.py", "foo2.py", "foo9.py"],
        ["foo0.py", "foo10.py", "fooa.py"],
    )


def test_bracket_inverted():
    assertMatchedAndNonMatched(
        ["foo[!1-9].py", "bar[!a].py"],
        ["fooa.py", "foob.py", "fooc.py", "barb.py", "barc.py"],
        ["foo1.py", "foo2.py", "foo10.py", "bara.py"],
    )


def test_slashes_in_brackets():
    assertMatchedAndNonMatched(
        [r"foo[\\].py"],
        [r"foo\.py"],
        [r"fooa.py"],
        # We don't test against git here, because it replies with "foo\\.py"
        # which is an escaped form that we'd have to interpret
        skip_git=True,
    )


def test_special_chars_in_brackets():
    assertMatchedAndNonMatched(
        [r"foo[a|b].py"],
        [r"fooa.py", "foob.py", "foo|.py"],
        [r"foo.py", r"fooc.py"],
    )
    assertMatchedAndNonMatched(
        [r"foo[ab|cd].py"],
        [r"fooa.py", "foob.py", "fooc.py", "food.py", "foo|.py"],
        [r"foo.py", "fooe.py", "fooab.py", "fooac.py"],
    )
    assertMatchedAndNonMatched(
        [r"foo[a&].py"],
        [r"fooa.py", r"foo&.py"],
        [r"foo.py", r"fooa&.py", "foob.py"],
    )
    assertMatchedAndNonMatched(
        [r"foo[a~].py"],
        [r"fooa.py", r"foo~.py"],
        [r"foo.py", r"fooa~.py", "foob.py"],
    )
    assertMatchedAndNonMatched(
        [r"foo[[a].py"],
        [r"fooa.py", r"foo[.py"],
        [r"foo.py", r"fooa[.py", "foob.py"],
    )
    # Git allows ! or ^ to mean negate the glob
    assertMatchedAndNonMatched(
        [r"foo[^a].py"],
        ["foob.py", "fooc.py", "foo^.py"],
        [r"foo.py", r"fooa.py", r"fooa^.py"],
    )


def test_extend_patterns():
    ignore = jujuignore.JujuIgnore(["foo"])
    assert ignore.match("foo", is_dir=False)
    assert not ignore.match("bar", is_dir=False)
    ignore.extend_patterns(["bar"])
    assert ignore.match("foo", is_dir=False)
    assert ignore.match("bar", is_dir=False)
