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

import argparse
import io
import os
import pathlib
import subprocess
import sys
from unittest.mock import patch

from charmcraft import __version__, logsetup
from charmcraft.main import Dispatcher, main, COMMAND_GROUPS
from charmcraft.cmdbase import BaseCommand, CommandError
from tests.factory import create_command

import pytest


@pytest.fixture(autouse=True)
def mock_is_charmcraft_running_in_supported_environment(monkeypatch):
    """Bypass entry point check for running as snap."""
    with patch(
        "charmcraft.env.is_charmcraft_running_in_supported_environment",
        return_value=True,
    ) as mock_supported:
        yield mock_supported


# --- Tests for the Dispatcher


def test_dispatcher_command_execution_ok():
    """Command execution depends of the indicated name in command line, return code ok."""

    class MyCommandControl(BaseCommand):
        help_msg = "some help"

        def run(self, parsed_args):
            self._executed.append(parsed_args)

    class MyCommand1(MyCommandControl):
        name = "name1"
        _executed = []

    class MyCommand2(MyCommandControl):
        name = "name2"
        _executed = []

    groups = [("test-group", "title", [MyCommand1, MyCommand2])]
    dispatcher = Dispatcher(["name2"], groups)
    dispatcher.run()
    assert MyCommand1._executed == []
    assert isinstance(MyCommand2._executed[0], argparse.Namespace)


def test_dispatcher_command_execution_crash():
    """Command crashing doesn't pass through, we inform nicely."""

    class MyCommand(BaseCommand):
        help_msg = "some help"
        name = "cmdname"

        def run(self, parsed_args):
            raise ValueError()

    groups = [("test-group", "title", [MyCommand])]
    dispatcher = Dispatcher(["cmdname"], groups)
    with pytest.raises(ValueError):
        dispatcher.run()


def test_dispatcher_config_needed_ok(tmp_path):
    """Command needs a config, which is provided ok."""

    class MyCommand(BaseCommand):
        help_msg = "some help"
        name = "cmdname"
        needs_config = True

        def run(self, parsed_args):
            pass

    # put the config in place
    test_file = tmp_path / "charmcraft.yaml"
    test_file.write_text(
        """
        type: charm
    """
    )

    groups = [("test-group", "title", [MyCommand])]
    dispatcher = Dispatcher(["cmdname", "--project-dir", tmp_path], groups)
    dispatcher.run()


def test_dispatcher_config_needed_problem(tmp_path):
    """Command needs a config, which is not there."""

    class MyCommand(BaseCommand):
        help_msg = "some help"
        name = "cmdname"
        needs_config = True

        def run(self, parsed_args):
            pass

    groups = [("test-group", "title", [MyCommand])]
    dispatcher = Dispatcher(["cmdname", "--project-dir", tmp_path], groups)
    with pytest.raises(CommandError) as err:
        dispatcher.run()
    assert str(err.value) == (
        "The specified command needs a valid 'charmcraft.yaml' configuration file (in the "
        "current directory or where specified with --project-dir option); see the reference: "
        "https://discourse.charmhub.io/t/charmcraft-configuration/4138"
    )


def test_dispatcher_config_not_needed():
    """Command does not needs a config."""

    class MyCommand(BaseCommand):
        help_msg = "some help"
        name = "cmdname"

        def run(self, parsed_args):
            pass

    groups = [("test-group", "title", [MyCommand])]
    dispatcher = Dispatcher(["cmdname"], groups)
    dispatcher.run()


def test_dispatcher_generic_setup_default():
    """Generic parameter handling for default values."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    logsetup.message_handler.mode = None
    with patch("charmcraft.config.load") as config_mock:
        Dispatcher(["somecommand"], groups)
    assert logsetup.message_handler.mode is None
    config_mock.assert_called_once_with(None)


@pytest.mark.parametrize(
    "options",
    [
        ["somecommand", "--verbose"],
        ["somecommand", "-v"],
        ["-v", "somecommand"],
        ["--verbose", "somecommand"],
        ["--verbose", "somecommand", "-v"],
    ],
)
def test_dispatcher_generic_setup_verbose(options):
    """Generic parameter handling for verbose log setup, directly or after the command."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    logsetup.message_handler.mode = None
    Dispatcher(options, groups)
    assert logsetup.message_handler.mode == logsetup.message_handler.VERBOSE


@pytest.mark.parametrize(
    "options",
    [
        ["somecommand", "--quiet"],
        ["somecommand", "-q"],
        ["-q", "somecommand"],
        ["--quiet", "somecommand"],
        ["--quiet", "somecommand", "-q"],
    ],
)
def test_dispatcher_generic_setup_quiet(options):
    """Generic parameter handling for quiet log setup, directly or after the command."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    logsetup.message_handler.mode = None
    Dispatcher(options, groups)
    assert logsetup.message_handler.mode == logsetup.message_handler.QUIET


@pytest.mark.parametrize(
    "options",
    [
        ["--quiet", "--verbose", "somecommand"],
        ["-v", "-q", "somecommand"],
        ["somecommand", "--quiet", "--verbose"],
        ["somecommand", "-v", "-q"],
        ["--verbose", "somecommand", "--quiet"],
        ["-q", "somecommand", "-v"],
    ],
)
def test_dispatcher_generic_setup_mutually_exclusive(options):
    """Disallow mutually exclusive generic options."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    # test the system exit, which is done automatically by argparse
    with pytest.raises(CommandError) as err:
        Dispatcher(options, groups)
    assert str(err.value) == "The 'verbose' and 'quiet' options are mutually exclusive."


@pytest.mark.parametrize(
    "options",
    [
        ["somecommand", "--project-dir", "foobar"],
        ["somecommand", "--project-dir=foobar"],
        ["somecommand", "-p", "foobar"],
        ["-p", "foobar", "somecommand"],
        ["--project-dir", "foobar", "somecommand"],
        ["--project-dir=foobar", "somecommand"],
    ],
)
def test_dispatcher_generic_setup_projectdir_with_param(options):
    """Generic parameter handling for 'project dir' with the param, directly or after the cmd."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    with patch("charmcraft.config.load") as config_mock:
        Dispatcher(options, groups)
    config_mock.assert_called_once_with("foobar")


@pytest.mark.parametrize(
    "options",
    [
        ["somecommand", "--project-dir"],
        ["somecommand", "--project-dir="],
        ["somecommand", "-p"],
        ["--project-dir=", "somecommand"],
    ],
)
def test_dispatcher_generic_setup_projectdir_without_param_simple(options):
    """Generic parameter handling for 'project dir' without the requested parameter."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    with pytest.raises(CommandError) as err:
        Dispatcher(options, groups)
    assert str(err.value) == "The 'project-dir' option expects one argument."


@pytest.mark.parametrize(
    "options",
    [
        ["-p", "somecommand"],
        ["--project-dir", "somecommand"],
    ],
)
def test_dispatcher_generic_setup_projectdir_without_param_confusing(options):
    """Generic parameter handling for 'project dir' taking confusingly the command as the arg."""
    cmd = create_command("somecommand")
    groups = [("test-group", "title", [cmd])]
    with pytest.raises(CommandError) as err:
        Dispatcher(options, groups)

    # generic usage message because "no command" (as 'somecommand' was consumed by --project-dir)
    assert "Usage" in str(err.value)


def test_dispatcher_build_commands_ok():
    """Correct command loading."""
    cmd0, cmd1, cmd2 = [create_command("cmd-name-{}".format(n), "cmd help") for n in range(3)]
    groups = [
        ("test-group-A", "whatever title", [cmd0]),
        ("test-group-B", "other title", [cmd1, cmd2]),
    ]
    dispatcher = Dispatcher([cmd0.name], groups)
    assert len(dispatcher.commands) == 3
    for cmd, group in [
        (cmd0, "test-group-A"),
        (cmd1, "test-group-B"),
        (cmd2, "test-group-B"),
    ]:
        expected_class, expected_group = dispatcher.commands[cmd.name]
        assert expected_class == cmd
        assert expected_group == group


def test_dispatcher_build_commands_repeated():
    """Error while loading commands with repeated name."""

    class Foo(BaseCommand):
        help_msg = "some help"
        name = "repeated"

    class Bar(BaseCommand):
        help_msg = "some help"
        name = "cool"

    class Baz(BaseCommand):
        help_msg = "some help"
        name = "repeated"

    groups = [
        ("test-group-1", "whatever title", [Foo, Bar]),
        ("test-group-2", "other title", [Baz]),
    ]
    expected_msg = "Multiple commands with same name: (Foo|Baz) and (Baz|Foo)"
    with pytest.raises(RuntimeError, match=expected_msg):
        Dispatcher([], groups)


def test_dispatcher_commands_are_not_loaded_if_not_needed():
    class MyCommand1(BaseCommand):
        """Expected to be executed."""

        name = "command1"
        help_msg = "some help"
        _executed = []

        def run(self, parsed_args):
            self._executed.append(parsed_args)

    class MyCommand2(BaseCommand):
        """Expected to not be instantiated, or parse args, or run."""

        name = "command2"
        help_msg = "some help"

        def __init__(self, *args):
            raise AssertionError

        def fill_parser(self, parser):
            raise AssertionError

        def run(self, parsed_args):
            raise AssertionError

    groups = [("test-group", "title", [MyCommand1, MyCommand2])]
    dispatcher = Dispatcher(["command1"], groups)
    dispatcher.run()
    assert isinstance(MyCommand1._executed[0], argparse.Namespace)


# --- Tests for the main entry point

# In all the test methods below we patch Dispatcher.run so we don't really exercise any
# command machinery, even if we call to main using a real command (which is to just
# make argument parsing system happy).


def test_main_ok():
    """Work ended ok: message handler notified properly, return code in 0."""
    with patch("charmcraft.main.message_handler") as mh_mock:
        with patch("charmcraft.main.Dispatcher.run") as d_mock:
            d_mock.return_value = None
            retcode = main(["charmcraft", "version"])

    assert retcode == 0
    mh_mock.ended_ok.assert_called_once_with()


def test_main_no_args():
    """The setup.py entry_point function needs to work with no arguments."""
    with patch("sys.argv", ["charmcraft"]):
        with patch("charmcraft.main.message_handler") as mh_mock:
            retcode = main()

    assert retcode == 1
    assert mh_mock.ended_cmderror.call_count == 1


def test_main_controlled_error():
    """Work raised CommandError: message handler notified properly, use indicated return code."""
    simulated_exception = CommandError("boom", retcode=33)
    with patch("charmcraft.main.message_handler") as mh_mock:
        with patch("charmcraft.main.Dispatcher.run") as d_mock:
            d_mock.side_effect = simulated_exception
            retcode = main(["charmcraft", "version"])

    assert retcode == 33
    mh_mock.ended_cmderror.assert_called_once_with(simulated_exception)


def test_main_environment_is_supported_error(
    mock_is_charmcraft_running_in_supported_environment,
):
    mock_is_charmcraft_running_in_supported_environment.return_value = False
    with patch("charmcraft.main.message_handler") as mh_mock:
        with patch("charmcraft.main.Dispatcher.run") as d_mock:
            d_mock.return_value = None
            retcode = main(["charmcraft", "version"])

    assert retcode == 1
    assert mh_mock.ended_cmderror.call_count == 1


def test_main_crash():
    """Work crashed: message handler notified properly, return code in 1."""
    simulated_exception = ValueError("boom")
    with patch("charmcraft.main.message_handler") as mh_mock:
        with patch("charmcraft.main.Dispatcher.run") as d_mock:
            d_mock.side_effect = simulated_exception
            retcode = main(["charmcraft", "version"])

    assert retcode == 1
    mh_mock.ended_crash.assert_called_once_with(simulated_exception)


def test_main_interrupted():
    """Work interrupted: message handler notified properly, return code in 1."""
    with patch("charmcraft.main.message_handler") as mh_mock:
        with patch("charmcraft.main.Dispatcher.run") as d_mock:
            d_mock.side_effect = KeyboardInterrupt
            retcode = main(["charmcraft", "version"])

    assert retcode == 1
    assert mh_mock.ended_interrupt.call_count == 1


# --- Tests for the bootstrap version message


def test_initmsg_default():
    """Without any option, the init msg only goes to disk."""
    cmd = create_command("somecommand")
    fake_stream = io.StringIO()
    with patch("charmcraft.main.COMMAND_GROUPS", [("test-group", "whatever title", [cmd])]):
        with patch.object(logsetup.message_handler, "ended_ok") as ended_ok_mock:
            with patch.object(logsetup.message_handler._stderr_handler, "stream", fake_stream):
                main(["charmcraft", "somecommand"])

    # get the logfile first line before removing it
    ended_ok_mock.assert_called_once_with()
    logged_to_file = pathlib.Path(logsetup.message_handler._log_filepath).read_text()
    file_first_line = logged_to_file.split("\n")[0]
    logsetup.message_handler.ended_ok()

    # get the terminal first line
    captured = fake_stream.getvalue()
    terminal_first_line = captured.split("\n")[0]

    expected = "Starting charmcraft version " + __version__
    assert expected in file_first_line
    assert expected not in terminal_first_line


def test_initmsg_quiet():
    """In quiet mode, the init msg only goes to disk."""
    cmd = create_command("somecommand")
    fake_stream = io.StringIO()
    with patch("charmcraft.main.COMMAND_GROUPS", [("test-group", "whatever title", [cmd])]):
        with patch.object(logsetup.message_handler, "ended_ok") as ended_ok_mock:
            with patch.object(logsetup.message_handler._stderr_handler, "stream", fake_stream):
                main(["charmcraft", "--quiet", "somecommand"])

    # get the logfile first line before removing it
    ended_ok_mock.assert_called_once_with()
    logged_to_file = pathlib.Path(logsetup.message_handler._log_filepath).read_text()
    file_first_line = logged_to_file.split("\n")[0]
    logsetup.message_handler.ended_ok()

    # get the terminal first line
    captured = fake_stream.getvalue()
    terminal_first_line = captured.split("\n")[0]

    expected = "Starting charmcraft version " + __version__
    assert expected in file_first_line
    assert expected not in terminal_first_line


def test_initmsg_verbose():
    """In verbose mode, the init msg goes both to disk and terminal."""
    cmd = create_command("somecommand")
    fake_stream = io.StringIO()
    with patch("charmcraft.main.COMMAND_GROUPS", [("test-group", "whatever title", [cmd])]):
        with patch.object(logsetup.message_handler, "ended_ok") as ended_ok_mock:
            with patch.object(logsetup.message_handler._stderr_handler, "stream", fake_stream):
                main(["charmcraft", "--verbose", "somecommand"])

    # get the logfile first line before removing it
    ended_ok_mock.assert_called_once_with()
    logged_to_file = pathlib.Path(logsetup.message_handler._log_filepath).read_text()
    file_first_line = logged_to_file.split("\n")[0]
    logsetup.message_handler.ended_ok()

    # get the terminal first line
    captured = fake_stream.getvalue()
    terminal_first_line = captured.split("\n")[0]

    expected = "Starting charmcraft version " + __version__
    assert expected in file_first_line
    assert expected in terminal_first_line


def test_commands():
    cmds = [cmd.name for _, _, cmds in COMMAND_GROUPS for cmd in cmds]

    env = os.environ.copy()

    # Bypass unsupported environment error.
    env["CHARMCRAFT_DEVELOPER"] = "1"

    env_paths = [p for p in sys.path if "env/lib/python" in p]
    if env_paths:
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] += ":" + ":".join(env_paths)
        else:
            env["PYTHONPATH"] = ":".join(env_paths)

    for cmd in cmds:
        subprocess.run(
            [sys.executable, "-m", "charmcraft", cmd, "-h"],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
        )
