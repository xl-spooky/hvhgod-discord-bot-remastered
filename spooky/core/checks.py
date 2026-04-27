"""Preflight checks and database-gating utilities for Spooky.

This module centralizes lightweight helpers used at startup and by commands to
determine whether database-backed features should run on this instance.

What this provides
------------------
- :func:`check_migrations`
    Detects whether the ``./migrations`` directory exists and logs a concise
    help message when it does not (useful during local/dev bootstrap).
- :func:`db_enabled`
    A cached boolean switch indicating whether DB-backed features should be
    considered enabled for this run (derived from :func:`check_migrations`).
- :func:`requires_database`
    A decorator returning a Disnake command check that **blocks** command
    execution gracefully when the database is unavailable, sending a short
    ephemeral notice to the invoker.
- :func:`run`
    A non-fatal preflight that logs any issues but never hard-fails startup.

Typical usage
-------------
Guard a DB-dependent command:

>>> from spooky.core.checks import requires_database
>>> @commands.slash_command()
... @requires_database()
... async def my_db_command(inter):
...     ...

Gate feature paths at runtime:

>>> if db_enabled():
...     # register or start DB-backed subsystems
...     ...

Notes
-----
- Startup should not depend on these checks; they are **advisory**. Runtime
  code should consult :func:`db_enabled` before using DB-backed features.
- The decorator sends an ephemeral message and marks the interaction with
  ``_spooky_error_sent = True`` (best-effort) to help upstream handlers avoid
  duplicate error responses.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar, cast

import disnake
from disnake.ext import commands
from loguru import logger
from spooky.bot import Spooky
from spooky.db import get_session
from spooky.models.entities.permissions import AppPermission, UserPermissionOverride
from sqlalchemy import select

T = TypeVar("T")


def check_migrations() -> bool:
    """Return whether the ``./migrations`` directory exists.

    When the directory is missing, logs a concise help message pointing to a
    typical bootstrap command (e.g., Docker-based migration invocation).

    Returns
    -------
    bool
        ``True`` if migrations exist; otherwise ``False``.

    Examples
    --------
    >>> check_migrations()
    True
    """
    has_migrations = Path("./migrations").exists()
    if not has_migrations:
        logger.error(
            "Can't find `migrations` directory!"
            "\n          HELP: Please migrate first"
            "\n          WITH: `docker compose run --rm migrate`"
        )
    return has_migrations


@lru_cache(maxsize=1)
def db_enabled() -> bool:
    """Return whether database-backed features should be enabled for this run.

    The value is cached for the process lifetime and is computed lazily from
    the presence of the ``./migrations`` directory via :func:`check_migrations`.

    Returns
    -------
    bool
        ``True`` if DB-backed features should be considered enabled, else ``False``.

    Notes
    -----
    - This is intentionally a coarse switch; it does not validate connectivity
      or engine health, only that migrations are present locally.
    """
    return Path("./migrations").exists()


def requires_database() -> Callable[[T], T]:  # type: ignore[override]
    """Deco that blocks command execution when the database is disabled.

    When blocked, the invoker receives an ephemeral message:
    ``"Database is not available on this instance."``

    Returns
    -------
    Callable[[T], T]
        A :func:`disnake.ext.commands.check` predicate suitable for slash/app commands.

    Examples
    --------
    >>> @commands.slash_command()
    ... @requires_database()
    ... async def my_db_command(inter): ...
    """

    async def predicate(inter: disnake.AppCmdInter[Spooky]) -> bool:
        """Check predicate for Disnake commands.

        Parameters
        ----------
        inter : disnake.AppCmdInter[Spooky]
            The incoming interaction.

        Returns
        -------
        bool
            ``True`` to allow command execution; ``False`` if blocked.
        """
        if not db_enabled():
            with suppress(Exception):
                await inter.response.send_message(
                    "Database is not available on this instance.",
                    ephemeral=True,
                )
                # Mark that an error message was already sent to avoid double-sends
                with suppress(Exception):
                    setattr(inter, "_spooky_error_sent", True)
            return False
        return True

    # Surface metadata for downstream introspection (e.g., help/analytics).
    setattr(
        predicate,
        "__spooky_check_meta__",
        {
            "name": "requires_database",
            "requires_database": True,
        },
    )

    # Disnake accepts interaction predicates at runtime,
    # but Pylance's stubs expect Context-based checks. Cast to satisfy types.
    return cast(Callable[[T], T], commands.check(cast(Any, predicate)))


def fakeperms_or_discordperm(permission: AppPermission | str) -> Callable[[T], T]:  # type: ignore[override]
    """Allow execution when user has Discord permission or fake-perm override.

    Parameters
    ----------
    permission : AppPermission | str
        Permission name (e.g. ``AppPermission.MANAGE_GUILD``).
    """
    perm_name = permission.value if isinstance(permission, AppPermission) else str(permission)

    async def predicate(ctx: commands.Context[Spooky] | disnake.AppCmdInter[Spooky]) -> bool:
        guild = getattr(ctx, "guild", None)
        actor = getattr(ctx, "author", None) or getattr(ctx, "user", None)
        if guild is None or actor is None:
            return False

        guild_permissions = getattr(actor, "guild_permissions", None)
        if guild_permissions is not None and bool(getattr(guild_permissions, perm_name, False)):
            return True

        if not db_enabled():
            return False

        async with get_session() as session:
            result = await session.execute(
                select(UserPermissionOverride.allowed)
                .where(
                    UserPermissionOverride.guild_id == int(guild.id),
                    UserPermissionOverride.user_id == int(actor.id),
                    UserPermissionOverride.perm_name == perm_name,
                )
                .order_by(UserPermissionOverride.id.desc())
                .limit(1)
            )
            allowed = result.scalar_one_or_none()

        return bool(allowed)

    setattr(
        predicate,
        "__spooky_check_meta__",
        {"name": "fakeperms_or_discordperm", "permission": perm_name},
    )

    return cast(Callable[[T], T], commands.check(cast(Any, predicate)))


def run() -> bool:
    """Run non-fatal preflight checks (logging issues as needed).

    Currently validates the presence of the ``./migrations`` directory. Startup
    never depends on this function's return value; DB-backed features should
    consult :func:`db_enabled` at runtime.

    Returns
    -------
    bool
        Always ``True`` (preflights are advisory and non-fatal).

    Examples
    --------
    >>> run()
    True
    """
    check_migrations()
    return True
