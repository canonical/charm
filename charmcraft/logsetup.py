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

"""Set up logging."""

import logging
import os
import tempfile

from charmcraft import __version__
from charmcraft.env import (
    get_managed_environment_log_path,
    is_charmcraft_running_in_managed_mode,
)

FORMATTER_SIMPLE = "%(message)s"
FORMATTER_DETAILED = "%(asctime)s  %(name)-40s %(levelname)-8s %(message)s"
FORMATTER_DETAILED_MANAGED = "mm %(asctime)s  %(name)-40s %(levelname)-8s %(message)s"

logger = logging.getLogger("charmcraft")
enabled_loggers = [
    logger,
    logging.getLogger("craft_providers"),
]


class _MessageHandler:
    """Handle all the messages to the user.

    This class deals with several combination of the following dimensions:

    - the mode: quiet, normal or verbose
    - the output: sometimes, some messages, to the terminal; always to the file
    - the execution result: what happens if succeeded, raise a controlled error, or crashed
    """

    _modes = {
        "quiet": (logging.WARNING, FORMATTER_SIMPLE),
        "normal": (logging.INFO, FORMATTER_SIMPLE),
        "verbose": (logging.DEBUG, FORMATTER_DETAILED),
    }

    def __init__(self):
        self._stderr_handler = logging.StreamHandler()
        for enabled_logger in enabled_loggers:
            enabled_logger.setLevel(logging.DEBUG)
            enabled_logger.addHandler(self._stderr_handler)

        # autoset modes constants for simpler interface
        for k in self._modes:
            setattr(self, k.upper(), k)

        self.mode = self.NORMAL

    def init(self, initial_mode):
        """Initialize internal structures; this must be done before start logging."""
        self._set_filehandler()
        self.set_mode(initial_mode)

    def set_mode(self, mode):
        """Set logging in different modes."""
        self.mode = mode
        level, format_string = self._modes[mode]
        self._stderr_handler.setFormatter(logging.Formatter(format_string))
        self._stderr_handler.setLevel(level)
        if mode == self.VERBOSE:
            logger.debug("Starting charmcraft version %s", __version__)

    def _set_filehandler(self):
        """Set the file handler to log everything to the temp file."""
        managed_mode = is_charmcraft_running_in_managed_mode()
        if managed_mode:
            self._log_filepath = str(get_managed_environment_log_path())
        else:
            _, self._log_filepath = tempfile.mkstemp(prefix="charmcraft-log-")

        file_handler = logging.FileHandler(self._log_filepath, mode="w")

        log_format = FORMATTER_DETAILED_MANAGED if managed_mode else FORMATTER_DETAILED

        file_handler.setFormatter(logging.Formatter(log_format))
        file_handler.setLevel(0)  # log eeeeeverything
        for enabled_logger in enabled_loggers:
            enabled_logger.addHandler(file_handler)

        # a logger for only the file
        self._file_logger = logging.getLogger("charmcraft.guard")
        self._file_logger.propagate = False
        self._file_logger.addHandler(file_handler)
        self._file_logger.debug("Starting charmcraft version %s", __version__)

    def ended_ok(self):
        """Cleanup after successful execution."""
        os.unlink(self._log_filepath)

    def ended_interrupt(self):
        """Clean up on keyboard interrupt."""
        if self.mode == self.VERBOSE:
            logger.exception("Interrupted.")
        else:
            logger.error("Interrupted.")
        os.unlink(self._log_filepath)

    def ended_cmderror(self, err):
        """Report the (expected) problem and (maybe) logfile location."""
        if err.argsparsing:
            print(err)
        else:
            msg = "{} (full execution logs in {!r})".format(err, str(self._log_filepath))
            logger.error(msg)

    def ended_crash(self, err):
        """Report the internal error and logfile location.

        Show just the error to the user, but send the whole traceback to the log file.
        """
        msg = "charmcraft internal error! {}: {} (full execution logs in {})".format(
            err.__class__.__name__, err, self._log_filepath
        )
        if self.mode == self.VERBOSE:
            # both to screen and file!
            logger.exception(msg)
        else:
            # the error to screen and file, plus the traceback to the file
            logger.error(msg)
            self._file_logger.exception("")


message_handler = _MessageHandler()
