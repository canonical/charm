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

"""Main entry point module for all the tool functionality."""

import argparse
import logging
import sys
from collections import namedtuple

from charmcraft import config, env, helptexts
from charmcraft.cmdbase import BaseCommand, CommandError
from charmcraft.commands import build, clean, init, pack, store, version
from charmcraft.logsetup import message_handler

logger = logging.getLogger(__name__)


class HelpCommand(BaseCommand):
    """Special internal command to produce help and usage messages.

    It bends the rules for parameters (we have an optional parameter without dashes), the
    idea is to lower the barrier as much as possible for the user getting help.
    """

    name = "help"
    help_msg = "Provide help on charmcraft usage"
    overview = "Produce a general or a detailed charmcraft help, or a specific command one."
    common = True

    def fill_parser(self, parser):
        """Add own parameters to the general parser."""
        parser.add_argument(
            "--all",
            action="store_true",
            help="Produce an extensive help of all commands",
        )
        parser.add_argument(
            "command_to_help",
            nargs="?",
            metavar="command",
            help="Produce a detailed help of the specified command",
        )

    def run(self, parsed_args, all_commands):
        """Present different help messages to the user.

        Unlike other commands, this one receives an extra parameter with all commands,
        to validate if the help requested is on a valid one, or even parse its data.
        """
        retcode = 0
        if parsed_args.command_to_help is None or parsed_args.command_to_help == self.name:
            # help on no command in particular, get general text
            help_text = get_general_help(detailed=parsed_args.all)
        elif parsed_args.command_to_help not in all_commands:
            # asked help on a command that doesn't exist
            msg = "no such command {!r}".format(parsed_args.command_to_help)
            help_text = helptexts.get_usage_message("charmcraft", msg)
            retcode = 1
        else:
            cmd_class, group = all_commands[parsed_args.command_to_help]
            cmd = cmd_class(group, None)
            parser = CustomArgumentParser(prog=cmd.name, add_help=False)
            cmd.fill_parser(parser)
            help_text = get_command_help(parser, cmd)
        raise CommandError(help_text, argsparsing=True, retcode=retcode)


# Collect commands in different groups, for easier human consumption. Note that this is not
# declared in each command because it's much easier to do this separation/grouping in one
# central place and not distributed in several classes/files. Also note that order here is
# important when listing commands and showing help.
COMMAND_GROUPS = [
    (
        "basic",
        "Basic",
        [
            HelpCommand,
            build.BuildCommand,
            clean.CleanCommand,
            pack.PackCommand,
            init.InitCommand,
            version.VersionCommand,
        ],
    ),
    (
        "store",
        "Charmhub",
        [
            # auth
            store.LoginCommand,
            store.LogoutCommand,
            store.WhoamiCommand,
            # name handling
            store.RegisterCharmNameCommand,
            store.RegisterBundleNameCommand,
            store.ListNamesCommand,
            # pushing files and checking revisions
            store.UploadCommand,
            store.ListRevisionsCommand,
            # release process, and show status
            store.ReleaseCommand,
            store.StatusCommand,
            # libraries support
            store.CreateLibCommand,
            store.PublishLibCommand,
            store.ListLibCommand,
            store.FetchLibCommand,
            # resources support
            store.ListResourcesCommand,
            store.UploadResourceCommand,
            store.ListResourceRevisionsCommand,
        ],
    ),
]


# global options: the name used internally, its type, short and long parameters, and help text
_Global = namedtuple("Global", "name type short_option long_option help_message")
GLOBAL_ARGS = [
    _Global("help", "flag", "-h", "--help", "Show this help message and exit"),
    _Global(
        "verbose",
        "flag",
        "-v",
        "--verbose",
        "Show debug information and be more verbose",
    ),
    _Global("quiet", "flag", "-q", "--quiet", "Only show warnings and errors, not progress"),
    _Global(
        "project_dir",
        "option",
        "-p",
        "--project-dir",
        "Specify the project's directory (defaults to current)",
    ),
]


class CustomArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with custom error manager.."""

    def error(self, message):
        """Show the usage, the error message, and no more."""
        fullcommand = "charmcraft " + self.prog
        full_msg = helptexts.get_usage_message(fullcommand, message)
        raise CommandError(full_msg, argsparsing=True)


def _get_global_options():
    """Return the global flags ready to present as options in the help messages."""
    options = []
    for arg in GLOBAL_ARGS:
        options.append(("{}, {}".format(arg.short_option, arg.long_option), arg.help_message))
    return options


def get_command_help(parser, command):
    """Produce the complete help message for a command."""
    options = _get_global_options()

    for action in parser._actions:
        # store the different options if present, otherwise it's just the dest
        if action.option_strings:
            options.append((", ".join(action.option_strings), action.help))
        else:
            dest = action.dest if action.metavar is None else action.metavar
            options.append((dest, action.help))

    help_text = helptexts.get_command_help(COMMAND_GROUPS, command, options)
    return help_text


def get_general_help(detailed=False):
    """Produce the "general charmcraft" help."""
    options = _get_global_options()
    if detailed:
        help_text = helptexts.get_detailed_help(COMMAND_GROUPS, options)
    else:
        help_text = helptexts.get_full_help(COMMAND_GROUPS, options)
    return help_text


class Dispatcher:
    """Set up infrastructure and let the needed command run.

    ♪♫"Leeeeeet, the command ruuun"♪♫ https://www.youtube.com/watch?v=cv-0mmVnxPA
    """

    def __init__(self, sysargs, commands_groups):
        self.commands = self._get_commands_info(commands_groups)
        command_name, cmd_args, charmcraft_config = self._pre_parse_args(sysargs)
        self.command, self.parsed_args = self._load_command(
            command_name, cmd_args, charmcraft_config
        )

    def _get_commands_info(self, commands_groups):
        """Process the commands groups structure for easier programmable access."""
        commands = {}
        for _cmd_group, _, _cmd_classes in commands_groups:
            for _cmd_class in _cmd_classes:
                if _cmd_class.name in commands:
                    _stored_class, _ = commands[_cmd_class.name]
                    raise RuntimeError(
                        "Multiple commands with same name: {} and {}".format(
                            _cmd_class.__name__, _stored_class.__name__
                        )
                    )
                commands[_cmd_class.name] = (_cmd_class, _cmd_group)
        return commands

    def _load_command(self, command_name, cmd_args, charmcraft_config):
        """Load a command."""
        cmd_class, group = self.commands[command_name]
        cmd = cmd_class(group, charmcraft_config)

        # load and parse the command specific options/params
        parser = CustomArgumentParser(prog=cmd.name)
        cmd.fill_parser(parser)
        parsed_args = parser.parse_args(cmd_args)
        logger.debug("Command parsed sysargs: %s", parsed_args)

        return cmd, parsed_args

    def _pre_parse_args(self, sysargs):
        """Pre-parse sys args.

        Several steps:

        - extract the global options and detects the possible command and its args

        - validate global options and apply them

        - validate that command is correct (NOT loading and parsing its arguments)
        """
        # get all arguments (default to what's specified) and those per options, to filter sysargs
        global_args = {}
        arg_per_option = {}
        options_with_equal = []
        for arg in GLOBAL_ARGS:
            arg_per_option[arg.short_option] = arg
            arg_per_option[arg.long_option] = arg
            if arg.type == "flag":
                default = False
            elif arg.type == "option":
                default = None
                options_with_equal.append(arg.long_option + "=")
            else:
                raise ValueError("Bad GLOBAL_ARGS structure.")
            global_args[arg.name] = default

        filtered_sysargs = []
        sysargs = iter(sysargs)
        options_with_equal = tuple(options_with_equal)
        for sysarg in sysargs:
            if sysarg in arg_per_option:
                arg = arg_per_option[sysarg]
                if arg.type == "flag":
                    value = True
                else:
                    try:
                        value = next(sysargs)
                    except StopIteration:
                        raise CommandError("The 'project-dir' option expects one argument.")
                global_args[arg.name] = value
            elif sysarg.startswith(options_with_equal):
                option, value = sysarg.split("=", 1)
                if not value:
                    raise CommandError("The 'project-dir' option expects one argument.")
                arg = arg_per_option[option]
                global_args[arg.name] = value
            else:
                filtered_sysargs.append(sysarg)

        # control and use quiet/verbose options
        if global_args["quiet"] and global_args["verbose"]:
            raise CommandError("The 'verbose' and 'quiet' options are mutually exclusive.")
        if global_args["quiet"]:
            message_handler.set_mode(message_handler.QUIET)
        elif global_args["verbose"]:
            message_handler.set_mode(message_handler.VERBOSE)
        logger.debug("Raw pre-parsed sysargs: args=%s filtered=%s", global_args, filtered_sysargs)

        # if help requested, transform the parameters to make that explicit
        if global_args["help"]:
            command = HelpCommand.name
            cmd_args = filtered_sysargs
        elif filtered_sysargs:
            command = filtered_sysargs[0]
            cmd_args = filtered_sysargs[1:]
            if command not in self.commands:
                msg = "no such command {!r}".format(command)
                help_text = helptexts.get_usage_message("charmcraft", msg)
                raise CommandError(help_text, argsparsing=True)
        else:
            # no command!
            help_text = get_general_help()
            raise CommandError(help_text, argsparsing=True)

        # load the system's config
        charmcraft_config = config.load(global_args["project_dir"])

        logger.debug("General parsed sysargs: command=%r args=%s", command, cmd_args)
        return command, cmd_args, charmcraft_config

    def run(self):
        """Really run the command."""
        if isinstance(self.command, HelpCommand):
            self.command.run(self.parsed_args, self.commands)
        else:
            if self.command.needs_config and not self.command.config.project.config_provided:
                raise CommandError(
                    "The specified command needs a valid 'charmcraft.yaml' configuration file (in "
                    "the current directory or where specified with --project-dir option); see "
                    "the reference: https://discourse.charmhub.io/t/charmcraft-configuration/4138"
                )
            self.command.run(self.parsed_args)


def main(argv=None):
    """Provide the main entry point."""
    message_handler.init(message_handler.NORMAL)

    if argv is None:
        argv = sys.argv

    # process
    try:
        env.ensure_charmcraft_environment_is_supported()
        dispatcher = Dispatcher(argv[1:], COMMAND_GROUPS)
        dispatcher.run()
    except CommandError as err:
        message_handler.ended_cmderror(err)
        retcode = err.retcode
    except KeyboardInterrupt:
        message_handler.ended_interrupt()
        retcode = 1
    except Exception as err:
        message_handler.ended_crash(err)
        retcode = 1
    else:
        message_handler.ended_ok()
        retcode = 0

    return retcode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
