"""Guards for per-guild command enable/disable.

This module provides utilities to **block execution** of commands when they have
been disabled in a guild via the settings panel. It also supports **per-role**
and **per-user** overrides and contains a small set of **protected** commands
that can never be disabled to avoid locking out configuration/administration.

Whats included
---------------
- :func:`is_command_protected` — Determine if a command is always enabled.
- :func:`ensure_command_enabled` — Guard that replies ephemerally when a command
  is disabled (guild-level disable or explicit deny override).
- :func:`require_command_enabled` — Decorator for commands to enforce the guard.
- Internal helpers:
  - ``_is_disabled`` — Check if a command is disabled for the guild.
  - ``_resolve_overrides`` — Resolve per-user/role overrides.

Precedence model
----------------
1. **Protected** commands are always enabled.
2. **Guild-level disable** blocks the command unless an explicit **allow**
   override exists (see below).
3. **User override** takes precedence over role overrides.
4. **Role overrides**:
   - Any **deny** for any member role → deny.
   - Otherwise any **allow** for any member role → allow.
   - Otherwise → fall through to guild-level state.

Examples
--------
Use as a decorator:

>>> @require_command_enabled()
... async def cmd(inter: disnake.AppCmdInter):
...     await inter.response.send_message("OK")

Manual guard inside a handler:

>>> if not await ensure_command_enabled(inter):
...     return  # already responded with an ephemeral denial

Notes
-----
- On denial, :func:`ensure_command_enabled` sends a standardized ephemeral
  :func:`spooky.ext.components.v2.card.status_card` and marks the
  interaction with ``_spooky_error_sent = True`` to help prevent duplicate
  error replies upstream.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import disnake
from disnake.ext import commands
from spooky.ext.components.v2.card import status_card
from spooky.models import GuildCommandDisabled, GuildCommandRoleOverride, GuildCommandUserOverride

__all__ = [
    "ensure_command_enabled",
    "is_command_protected",
    "normalize_command_key",
    "require_command_enabled",
]

_ALWAYS_ENABLED: set[str] = {
    "configuration",
    "configuration guild",
    "configuration user",
    "help",
    "prefix",
    "prefix guild",
    "prefix status",
    "prefix user",
}

_MESSAGE_PREFIX = "message:"
_MODALITY_PREFIXES = (_MESSAGE_PREFIX, "interaction:")


def is_command_protected(name: str) -> bool:
    """Return ``True`` if the command name is protected (cannot be disabled).

    Parameters
    ----------
    name : str
        Command's qualified name (e.g., ``"configuration"`` or ``"admin purge"``).

    Returns
    -------
    bool
        ``True`` if the command is considered always-on; otherwise ``False``.
    """
    normalized = name.lower()
    for prefix in _MODALITY_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized in _ALWAYS_ENABLED


def normalize_command_key(name: str, *, modality: str | None = None) -> str:
    """Return the canonical key used for storing command gate state.

    Parameters
    ----------
    name : str
        Raw command name or qualified path as exposed by the bot.
    modality : str | None, optional
        Command modality (``"message"`` or ``"interaction"``). When ``"message"``
        the normalized key is prefixed with ``"message:"`` so message and
        interaction variants of the same command can be configured separately.

    Returns
    -------
    str
        Lowercase canonical key. Returns an empty string when ``name`` is blank.
    """
    normalized = (name or "").strip().lower()
    if not normalized:
        return ""
    if modality == "message" and not normalized.startswith(_MESSAGE_PREFIX):
        return f"{_MESSAGE_PREFIX}{normalized}"
    return normalized


F = TypeVar("F", bound=Callable[..., Any])


def _guild_id_from_target(
    target: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
) -> int | None:
    """Return the guild ID for an interaction or context (if available)."""
    gid = getattr(target, "guild_id", None)
    if gid is not None:
        try:
            return int(gid)
        except (TypeError, ValueError):
            return None

    guild = getattr(target, "guild", None)
    if guild is not None:
        return getattr(guild, "id", None)

    return None


async def _is_disabled(
    target: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
    *,
    command_name: str,
) -> bool:
    """Check if the command is disabled at the guild level.

    Parameters
    ----------
    inter :
        The interaction providing guild context.
    command_name : str
        The command's qualified name (case-insensitive).

    Returns
    -------
    bool
        ``True`` if a matching row exists in :class:`GuildCommandDisabled`.
    """
    gid = _guild_id_from_target(target)
    if gid is None:
        return False
    try:
        return (
            await GuildCommandDisabled.filter(
                guild_id=int(gid),
                command=command_name.lower(),
            )
            .limit(1)
            .exists()
        )
    except Exception:
        return False


async def _resolve_overrides(
    target: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
    *,
    command_name: str,
) -> bool | None:
    """Resolve explicit per-user/role overrides for a command.

    Resolution rules
    ----------------
    - If a **user override** exists, return its boolean immediately.
    - Else, if any **role deny** exists for the member, return ``False``.
    - Else, if any **role allow** exists, return ``True``.
    - Else, return ``None`` (no explicit override).

    Parameters
    ----------
    inter :
        The interaction that includes the user/member and guild context.
    command_name : str
        Command qualified name (case-insensitive).

    Returns
    -------
    bool | None
        ``True`` for explicit allow, ``False`` for explicit deny, or ``None`` if no override.
    """
    gid = _guild_id_from_target(target)
    if gid is None:
        return None

    author = getattr(target, "author", None) or getattr(target, "user", None)
    uid = getattr(author, "id", None)
    try:
        name = command_name.lower()
    except Exception:
        name = command_name

    try:
        # User-specific override takes precedence over role-level allows/denies.
        if uid is not None:
            rows = (
                await GuildCommandUserOverride.filter(
                    guild_id=int(gid),
                    user_id=int(uid),
                    command=name,
                )
                .limit(1)
                .values_list("allowed", flat=True)
            )
            if rows:
                allowed = bool(rows[0])
                return allowed

        member = author
        role_ids: list[int] = []
        if isinstance(member, disnake.Member):
            role_ids = [int(role.id) for role in getattr(member, "roles", [])]

        if role_ids:
            deny_exists = (
                await GuildCommandRoleOverride.filter(
                    guild_id=int(gid),
                    command=name,
                    allowed=False,
                    role_id__in=role_ids,
                )
                .limit(1)
                .exists()
            )
            if deny_exists:
                return False

            allow_exists = (
                await GuildCommandRoleOverride.filter(
                    guild_id=int(gid),
                    command=name,
                    allowed=True,
                    role_id__in=role_ids,
                )
                .limit(1)
                .exists()
            )
            if allow_exists:
                return True
    except Exception:
        return None

    return None


async def ensure_command_enabled(
    inter: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
    *,
    command_name: str | None = None,
) -> bool:
    """Return ``True`` if the command is enabled; otherwise reply & return ``False``.

    This guard enforces the per-guild disable list and consults user/role
    overrides. Protected commands always pass.

    Parameters
    ----------
    inter :
        The incoming interaction.
    command_name : str | None, optional
        The command's qualified name. If omitted, attempts to read from
        ``inter.application_command.qualified_name``.

    Returns
    -------
    bool
        ``True`` when execution should proceed; otherwise ``False`` after an
        ephemeral denial message has been sent.

    Notes
    -----
    - On denial, the function responds ephemerally and sets
      ``inter._spooky_error_sent = True`` (best-effort) to prevent duplicate error replies.
    """
    if command_name is not None:
        command_name = command_name.strip().lower()

    if command_name is None:
        if isinstance(inter, commands.Context):
            command = getattr(inter, "command", None)
            raw_name = None
            if command is not None:
                raw_name = getattr(command, "qualified_name", None)
                if not raw_name:
                    raw_name = getattr(command, "name", None)
            if isinstance(raw_name, str):
                command_name = normalize_command_key(raw_name, modality="message")
            else:
                command_name = None
        else:
            try:
                cmd = getattr(inter, "application_command", None)
                if cmd is not None:
                    command_name = normalize_command_key(cast(str, cmd.qualified_name))
            except Exception:
                command_name = None

    if not command_name:
        return True

    if is_command_protected(command_name):
        return True

    try:
        override = await _resolve_overrides(inter, command_name=command_name)
    except Exception:
        override = None

    if override is False:
        await _send_denial(inter, "You do not have access to this command here.")
        return False

    if override is True:
        return True

    if await _is_disabled(inter, command_name=command_name):
        await _send_denial(inter, "This command is disabled in this guild.")
        return False

    return True


def require_command_enabled() -> Callable[[F], F]:
    """Return a :func:`disnake.ext.commands.check` that blocks disabled commands.

    Use this decorator on slash/app commands to ensure the command is not
    disabled in the current guild (unless it is protected or explicitly
    allowed via user/role overrides).

    Returns
    -------
    Callable[[F], F]
        A decorator compatible with Disnake command callbacks.
    """

    async def predicate(
        inter: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
    ) -> bool:  # type: ignore[override]
        cmd_name: str | None = None
        if isinstance(inter, commands.Context):
            command = getattr(inter, "command", None)
            raw_name = None
            if command is not None:
                raw_name = getattr(command, "qualified_name", None)
                if not raw_name:
                    raw_name = getattr(command, "name", None)
            if isinstance(raw_name, str):
                cmd_name = normalize_command_key(raw_name, modality="message")
        else:
            try:
                cmd = getattr(inter, "application_command", None)
                if cmd is not None:
                    cmd_name = normalize_command_key(cast(str, cmd.qualified_name))
            except Exception:
                cmd_name = None
        return await ensure_command_enabled(inter, command_name=cmd_name)

    setattr(
        predicate,
        "__spooky_check_meta__",
        {
            "name": "require_command_enabled",
        },
    )

    return cast(Callable[[F], F], commands.check(cast(Any, predicate)))


async def _send_denial(
    target: disnake.AppCmdInter[Any] | disnake.MessageInteraction[Any] | commands.Context[Any],
    message: str,
) -> None:
    """Send a standardized denial response for interactions or contexts."""
    if isinstance(target, commands.Context):
        try:
            warning = getattr(target, "warning", None)
            if callable(warning):
                await cast(Awaitable[Any], warning(message))
            else:
                await target.send(embed=status_card(False, message))
        except Exception:
            pass
        return

    try:
        if getattr(target.response, "is_done", lambda: False)():
            await target.followup.send(
                embed=status_card(False, message),
                ephemeral=True,
            )
        else:
            await target.response.send_message(
                embed=status_card(False, message),
                ephemeral=True,
            )
        with contextlib.suppress(Exception):
            setattr(target, "_spooky_error_sent", True)
    except Exception:
        pass
