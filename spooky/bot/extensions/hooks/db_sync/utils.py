"""Utility helpers for database readiness, safe deletion, and loop cancellation.

This module centralizes low-level safety helpers commonly used during
database synchronization or cleanup routines. It ensures that database work
is only executed when the environment is ready, and provides consistent,
telemetry-backed failure handling.

Functions
---------
guard_db_ready
    Ensure DB operations are permitted and the bot is fully initialized.
safe_delete
    Execute a database DELETE with telemetry and defensive error handling.
safe_cancel
    Cancel long-running or looping tasks without raising teardown exceptions.
"""

from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger
from spooky.bot import Spooky
from spooky.core import checks
from spooky.core.telemetry import send_exception
from spooky.db import get_session
from sqlalchemy import delete


async def guard_db_ready(bot: Spooky) -> bool:
    """Check that the database is enabled and the bot client is ready.

    This helper short-circuits DB work when persistence is disabled, and
    ensures the client is fully initialized before continuing.

    Parameters
    ----------
    bot : Spooky
        The running :class:`~spooky.bot.Spooky` instance.

    Returns
    -------
    bool
        ``True`` if DB sync work may proceed, otherwise ``False``.
    """
    if not checks.db_enabled():
        return False
    await bot.wait_until_ready()
    return True


async def safe_delete(
    bot: Spooky,
    model: type[Any],
    *conditions: Any,
    title: str,
    description: str,
) -> int | None:
    """Execute a DELETE against ``model`` with optional ``WHERE`` conditions.

    All execution is wrapped with telemetry; failures are logged and reported
    via :func:`send_exception`. Returns the number of affected rows when
    available.

    Parameters
    ----------
    bot : Spooky
        The running :class:`~spooky.bot.Spooky` instance (for telemetry context).
    model : type[Any]
        ORM model/table to delete from.
    *conditions : Any
        Optional SQLAlchemy boolean expressions applied as ``WHERE`` clauses.
        If omitted, **all** rows of ``model`` are targeted.
    title : str
        Short, human-readable label for telemetry/logging.
    description : str
        Additional context included with telemetry (e.g., counts, guild IDs).

    Returns
    -------
    int | None
        Number of deleted rows if provided by the driver; otherwise ``0``.
        Returns ``None`` when an exception occurs.

    Notes
    -----
    - Transaction/commit behavior depends on :func:`get_session`. This function
      assumes the session context manager handles committing/rolling back.
    - Keep ``title`` and ``description`` concise but informative to aid
      dashboards and error triage.
    """
    try:
        async with get_session() as session:
            stmt = delete(model)
            if conditions:
                stmt = stmt.where(*conditions)
            result = await session.execute(stmt)
            rowcount = int(getattr(result, "rowcount", 0) or 0)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("{}: {}", title, e)
        await send_exception(bot, title=title, description=description, error=e)
        return None

    return rowcount


def safe_cancel(loop_task: Any) -> None:
    """Cancel a :mod:`disnake.ext.tasks` loop safely.

    Suppresses non-critical exceptions thrown by ``Loop.cancel()`` to avoid
    noisy teardown during cog reloads or shutdown.

    Parameters
    ----------
    loop_task : Any
        A :class:`disnake.ext.tasks.Loop` (or loop-like object exposing ``cancel()``).
    """
    with contextlib.suppress(Exception):
        loop_task.cancel()
