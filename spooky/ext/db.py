"""Helpers for reusable boolean flag patterns using SQLAlchemy queries.

This module provides utility functions that simplify toggling and retrieving
boolean fields (flags) from database models using the project's
:class:`~spooky.models.query.QueryBuilder`.

It supports two common use cases:

1. **Fetching a boolean flag safely** with fallbacks, even if the row is missing.
2. **Setting a boolean flag** with optional creation logic when no matching row exists.

Typical usage
-------------
>>> enabled = await fetch_bool_flag(
...     MyModel.filter(guild_id=123),
...     field="feature_enabled",
...     default=False,
... )

>>> await set_bool_flag(
...     MyModel,
...     filters={"guild_id": 123},
...     field="feature_enabled",
...     value=True,
...     create_when_true=True,
... )

Notes
-----
- These helpers abstract repetitive toggle logic commonly used in per-guild or
  per-user settings tables.
- They rely on the project's session manager (:func:`spooky.db.get_session`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from spooky.db import get_session
from spooky.models.base_models.base import Base
from sqlalchemy import update

if TYPE_CHECKING:
    from spooky.models.query import QueryBuilder

__all__ = ["fetch_bool_flag", "set_bool_flag"]


async def fetch_bool_flag(
    query: QueryBuilder[Any],
    *,
    field: str,
    default: bool = False,
) -> bool:
    """Return the first boolean value from a query, falling back to a default.

    Parameters
    ----------
    query : QueryBuilder[Any]
        A query builder instance scoped to the target table and filters.
    field : str
        Name of the boolean column to retrieve.
    default : bool, optional
        Value to return if no row exists, or if the query fails. Defaults to ``False``.

    Returns
    -------
    bool
        The first row's value for ``field`` if available; otherwise ``default``.

    Notes
    -----
    - Internally performs ``query.values_list(field, flat=True)``.
    - Any exceptions (e.g., invalid field or query errors) result in ``default``.
    """
    try:
        rows = await query.values_list(field, flat=True)
    except Exception:
        return bool(default)
    if not rows:
        return bool(default)
    return bool(rows[0])


async def set_bool_flag(
    model: type[Base],
    *,
    filters: Mapping[str, Any],
    field: str,
    value: bool,
    create_when_true: bool = True,
    create_when_false: bool = False,
) -> bool:
    """Update a boolean flag, optionally creating the row if it doesn't exist.

    Parameters
    ----------
    model : type[Base]
        SQLAlchemy model to operate on.
    filters : Mapping[str, Any]
        A dict of field/value pairs used to select the target row(s).
    field : str
        Name of the boolean column to update.
    value : bool
        Boolean to set.
    create_when_true : bool, optional
        If ``True`` and no rows are updated, a new row is created when ``value`` is True.
        Defaults to ``True``.
    create_when_false : bool, optional
        If ``True`` and no rows are updated, a new row is created when ``value`` is False.
        Defaults to ``False``.

    Returns
    -------
    bool
        ``True`` if a row was updated or created; ``False`` if no changes occurred.

    Notes
    -----
    - Uses :func:`sqlalchemy.update` under the hood.
    - Leverages :meth:`QueryBuilder.where_clause` for filter composition.
    - If no row is updated and creation is allowed (based on ``create_when_*``),
      a new instance is inserted using ``filters`` + ``field``.
    """
    payload = {field: bool(value)}
    builder = model.filter(**filters)
    where = builder.where_clause()

    async with get_session() as session:
        stmt = update(model).values(**payload)
        if where is not None:
            stmt = stmt.where(where)
        result = await session.execute(stmt)
        updated = getattr(result, "rowcount", None) or 0

        should_create = updated == 0 and (
            (value and create_when_true) or (not value and create_when_false)
        )
        if should_create:
            data = dict(filters)
            data.update(payload)
            session.add(model(**data))
            await session.flush()
            return True
        return updated > 0
