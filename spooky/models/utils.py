"""Database helper utilities for Spooky models.

This module centralizes a few small, high-level helpers around our SQLAlchemy
**async** stack so feature code can:
- Lazily fetch-or-create core entities (`Guild`, `User`) in a single call.
- Ensure many rows exist in bulk without round-tripping per-row.
- Compute shallow, field-based diffs between two plain objects (e.g., ORM instances).

Notes
-----
- All DB helpers use our projects `get_session()` coroutine to acquire an
  **async** SQLAlchemy session, and will `flush()` after creating missing rows
  so their primary keys are immediately available.
- Errors from SQLAlchemy (e.g., connection issues, constraint violations) are
  not swallowed; they propagate to callers so higher layers can decide whether
  to retry, log, or surface the failure.

Examples
--------
Basic usage (inside an async context):

>>> guild = await fetch_db_guild(123456789012345678)
>>> user = await fetch_db_user(987654321098765432)
>>> created, existing = await bulk_ensure_guilds([1, 2, 3])
>>> changes = get_model_changes(old_obj, new_obj, ("name", "icon", "owner_id"))
"""

from __future__ import annotations

from collections import abc
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

from loguru import logger
from spooky.db import get_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .base_models.guild import Guild
from .base_models.user import User

__all__ = [
    "bulk_ensure_guilds",
    "bulk_ensure_users",
    "fetch_db_guild",
    "fetch_db_user",
    "get_model_changes",
]

T = TypeVar("T")


@lru_cache(maxsize=1)
def _get_session_factory() -> Callable[..., Any]:
    return get_session


async def fetch_db_guild(guild_id: int) -> Guild:
    """Fetch (or create) the :class:`Guild` row for a given ID.

    Parameters
    ----------
    guild_id:
        The Discord guild identifier (snowflake) to look up.

    Returns
    -------
    Guild
        The existing row if found, otherwise a newly created, **flushed**
        `Guild(id=guild_id)` instance.

    Raises
    ------
    sqlalchemy.exc.SQLAlchemyError
        Propagates any DB/driver error encountered during query or flush.

    Notes
    -----
    - If the row does not exist, this function **adds** it to the current
      session and calls ``flush()`` so downstream code can safely rely on the
      instance being persistent within the transaction.
    - This helper does **not** commit; transaction boundaries are owned by
      the session manager (`get_session()` context).
    """
    logger.debug("Fetching guild {}", guild_id)
    get_session = _get_session_factory()
    async with get_session() as session:
        result = await session.execute(select(Guild).where(Guild.id == guild_id))
        guild = result.scalar_one_or_none()
        if guild is None:
            guild = Guild(id=guild_id)
            session.add(guild)
            await session.flush()
        return guild


async def fetch_db_user(user_id: int) -> User:
    """Fetch (or create) the :class:`User` row for a given ID.

    Parameters
    ----------
    user_id:
        The Discord user identifier (snowflake) to look up.

    Returns
    -------
    User
        The existing row if found, otherwise a newly created, **flushed**
        `User(id=user_id)` instance.

    Raises
    ------
    sqlalchemy.exc.SQLAlchemyError
        Propagates any DB/driver error encountered during query or flush.

    Notes
    -----
    - If the row does not exist, this function **adds** it to the current
      session and calls ``flush()`` so downstream code can safely rely on the
      instance being persistent within the transaction.
    - This helper does **not** commit; transaction boundaries are owned by
      the session manager (`get_session()` context).
    """
    logger.debug("Fetching user {}", user_id)
    get_session = _get_session_factory()
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            await session.execute(
                insert(User).values(id=user_id).on_conflict_do_nothing(index_elements=[User.id])
            )
            await session.flush()

            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
        return user


async def bulk_ensure_guilds(ids: abc.Iterable[int]) -> tuple[int, int]:
    """Ensure that :class:`Guild` rows exist for all provided IDs.

    Parameters
    ----------
    ids:
        Iterable of Discord guild IDs (snowflakes). Duplicates are ignored.

    Returns
    -------
    tuple[int, int]
        A ``(created, existing)`` pair indicating how many rows were inserted
        in this call and how many were already present.

    Raises
    ------
    sqlalchemy.exc.SQLAlchemyError
        Propagates any DB/driver error encountered during query or flush.

    Notes
    -----
    - Performs a single SELECT with ``IN`` against the provided ID set, then
      inserts any missing IDs in one batch via ``session.add_all`` followed by
      ``flush()``.
    - This helper is idempotent and safe to call repeatedly with overlapping
      ID sets (within the same transaction, inserted rows will be visible).
    """
    id_set = set(ids)
    if not id_set:
        return 0, 0

    get_session = _get_session_factory()
    async with get_session() as session:
        existing_rows = await session.execute(select(Guild.id).where(Guild.id.in_(list(id_set))))
        existing_set = set(existing_rows.scalars())
        missing = id_set - existing_set
        if missing:
            session.add_all([Guild(id=i) for i in missing])
            await session.flush()
        return len(missing), len(existing_set)


async def bulk_ensure_users(ids: abc.Iterable[int]) -> tuple[int, int]:
    """Ensure that :class:`User` rows exist for all provided IDs.

    Parameters
    ----------
    ids:
        Iterable of Discord user IDs (snowflakes). Duplicates are ignored.

    Returns
    -------
    tuple[int, int]
        A ``(created, existing)`` pair indicating how many rows were inserted
        in this call and how many were already present.

    Raises
    ------
    sqlalchemy.exc.SQLAlchemyError
        Propagates any DB/driver error encountered during query or flush.

    Notes
    -----
    - Performs a single SELECT with ``IN`` against the provided ID set, then
      inserts any missing IDs in one batch via ``session.add_all`` followed by
      ``flush()``.
    - This helper is idempotent and safe to call repeatedly with overlapping
      ID sets (within the same transaction, inserted rows will be visible).
    """
    id_set = set(ids)
    if not id_set:
        return 0, 0

    get_session = _get_session_factory()
    async with get_session() as session:
        existing_rows = await session.execute(select(User.id).where(User.id.in_(list(id_set))))
        existing_set = set(existing_rows.scalars())
        missing = id_set - existing_set
        if missing:
            session.add_all([User(id=i) for i in missing])
            await session.flush()
        return len(missing), len(existing_set)


def get_model_changes(obj1: T, obj2: T, fields_to_check: abc.Iterable[str]) -> list[str]:
    """Compute a shallow field diff between two objects.

    Parameters
    ----------
    obj1:
        The *baseline* object to compare from (e.g., existing ORM instance).
    obj2:
        The *candidate* object to compare to (e.g., mutated copy or payload).
    fields_to_check:
        Iterable of attribute names to compare. Missing attributes are treated
        as ``None``.

    Returns
    -------
    list[str]
        A list of field names whose values differ when comparing
        ``getattr(obj1, field, None)`` vs. ``getattr(obj2, field, None)``.

    Notes
    -----
    - Comparison is **shallow** and uses Python's ``!=`` semantics for each
      attribute value.
    - Useful for building ``UPDATE`` statements or change logs without
      over-inspecting large objects.
    """
    changed_fields: list[str] = []
    for field in fields_to_check:
        value1 = getattr(obj1, field, None)
        value2 = getattr(obj2, field, None)
        if value1 != value2:
            changed_fields.append(field)
    return changed_fields
