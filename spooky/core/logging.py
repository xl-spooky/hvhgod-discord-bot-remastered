"""Log configuration and stdlib-to-Loguru interception.

This module standardizes logging across the application by:
- Configuring Loguru as the primary logger.
- Redirecting all standard-library ``logging`` messages (including from
  third-party dependencies) into Loguru for consistent formatting and
  structured output.

This ensures that both internal logs and third-party library logs appear in
a unified format, respecting the configured log level and sinks.

Components
----------
- :class:`InterceptHandler` :
    A custom ``logging.Handler`` that forwards stdlib log records to Loguru,
    preserving level, exception information, and caller location.
- :func:`setup` :
    Initializes Loguru, installs stderr sinks, and globally sets
    ``InterceptHandler`` as the handler for stdlib logging.

Typical Flow
------------
Called once during application startup:

>>> from spooky.core import logs
>>> logs.setup()

After that:
- Calls to ``loguru.logger`` work normally.
- Calls to ``logging.getLogger(__name__).info(...)`` are also routed into Loguru.

Notes
-----
- Caller depth correction is applied so file/line references accurately reflect
  the original call site instead of internal logging handlers.
- Log level defaults to ``settings.log.level``, but can be overridden.
- All prior Loguru sinks are removed before new configuration is applied.

"""

from __future__ import annotations

import inspect
import logging
import sys

from loguru import logger
from spooky.core import settings


class InterceptHandler(logging.Handler):
    """Route stdlib logging records into Loguru.

    Converts built-in logging records to Loguru messages, preserving levels,
    exceptions, and the original caller depth for accurate file/line reporting.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a stdlib record to Loguru.

        Determines the appropriate Loguru level, walks back call frames to skip the
        stdlib logging internals, and logs the message with exception info.

        Parameters
        ----------
        record : logging.LogRecord
            The log record to emit.
        """
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = inspect.currentframe()
        depth = 6
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup(level: str = settings.log.level) -> None:
    """Configure Loguru and redirect stdlib logging.

    Removes existing Loguru sinks, adds a colorized stderr sink, and installs an
    :class:`InterceptHandler` so any ``logging`` usage flows into Loguru.

    Parameters
    ----------
    level : str, optional
        Log level for the Loguru sink (e.g., ``"INFO"``, ``"DEBUG"``).
        Defaults to the value from settings.
    """
    logger.remove()
    logger.add(sys.stderr, level=level or "DEBUG", colorize=True)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
