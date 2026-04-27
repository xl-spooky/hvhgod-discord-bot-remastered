"""Project-wide exception hierarchy for Spooky.

This module defines custom exceptions used across the project to distinguish between:
1. **User-facing errors** - Fail with a safe, friendly message intended for
   Discord responses (e.g. invalid input, missing permissions).
2. **Operational failures** - Unexpected internal errors that should be logged
   or sent to telemetry with diagnostic context.
3. **Entity lookup failures** - Common structured exception type for resolving
   Discord objects (users, guilds, channels, roles, etc.).

Using a unified exception hierarchy simplifies error handling across commands,
views, middleware, and background tasks.

Usage guidance
--------------
- Raise :class:`UserMessageError` when the *end user* should receive the message.
- Raise or wrap unexpected failures in :class:`SpookyUnhandledCommandError`
  (often used to trigger a common fallback error response).
- Raise :class:`EntityResolutionError` when data lookup fails so that telemetry
  and UI responders can include structured debugging info.
- Do not raise :class:`SpookyError` directly unless subclassing.

Typical Discord command flow
----------------------------
>>> if not user_data:
...     raise UserMessageError("You must register first.")
>>> try:
...     risky_db_call()
... except Exception as exc:
...     raise SpookyUnhandledCommandError(exc)

Telemetry can catch :class:`EntityResolutionError` for contextual reporting.

"""

from __future__ import annotations

from disnake.ext import commands


class SpookyError(Exception):
    """Base exception for Spooky-specific errors.

    All custom exceptions should inherit from this class so higher-level
    handlers can catch and process Spooky-related failures uniformly.
    """


class UserMessageError(SpookyError):
    """Represents a safe, user-facing error message.

    Store a short, friendly explanation in ``message``. This is meant to be
    surfaced directly to Discord users (e.g., via :func:`status_card`) without
    requiring additional formatting.

    Parameters
    ----------
    message : str
        Human-readable text that will be shown to the user.

    Notes
    -----
    - Avoid exposing internal details or stack traces.
    - Typical usage in validation or permission errors.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class SpookyUnhandledCommandError(SpookyError):
    """Represents an unexpected failure during command execution.

    Intended for situations where an exception occurs that was not recoverable
    or expected. This exception acts as a boundary so that a common fallback
    error message (e.g., "Something went wrong") can be shown to users, while
    the original exception is logged or sent to telemetry.

    Parameters
    ----------
    original : BaseException | None, optional
        The underlying exception that triggered this error, if any.
    """

    def __init__(self, original: BaseException | None = None) -> None:
        msg = "Unhandled command error"
        super().__init__(msg)
        self.original = original


class EntityResolutionError(SpookyError):
    """Raised when a Discord entity cannot be resolved.

    Used in lookup helper functions to indicate failure to find or fetch an
    expected entity from cache or REST. This structured error type improves
    logging and telemetry diagnostic output.

    Parameters
    ----------
    entity : str
        The type of entity being resolved (e.g., ``"User"``, ``"Guild"``).
    identifiers : dict[str, int | str]
        Key/value identifiers used for lookup
        (e.g., ``{"guild_id": 1, "user_id": 2}``).
    detail : str | None, optional
        Optional human-readable explanation of why resolution failed
        (e.g., ``"missing permissions"`` or ``"guild unavailable"``).

    Attributes
    ----------
    entity : str
        Entity type.
    identifiers : dict[str, int | str]
        Identifiers provided.
    detail : str | None
        Optional explanation or reason for failure.
    """

    def __init__(
        self, entity: str, identifiers: dict[str, int | str], *, detail: str | None = None
    ) -> None:
        msg = f"Failed to resolve {entity}: {identifiers}"
        if detail:
            msg = f"{msg} ({detail})"
        super().__init__(msg)
        self.entity = entity
        self.identifiers = identifiers
        self.detail = detail


class MissingSubcommandError(commands.UserInputError, SpookyError):
    """Raised when a command group is invoked without a subcommand.

    Parameters
    ----------
    command_name : str
        Fully qualified command name (e.g., ``"prefix"`` or ``"prefix group"``).
    """

    def __init__(self, command_name: str) -> None:
        message = f"Missing subcommand for `{command_name}`."
        commands.UserInputError.__init__(self, message)
        SpookyError.__init__(self, message)
        self.command_name = command_name
