"""QueryBuilder: a small, typed async query helper on top of SQLAlchemy Core.

This module provides an ergonomic, chainable API (inspired by Tortoise/Django)
for constructing **read-mostly** queries against SQLAlchemy async sessions.
It focuses on:
- A typed, chainable :class:`QueryBuilder` for a mapped model.
- A compact filter language using ``field__lookup=value`` keys.
- Simple ordering (``"name"`` or ``"-created_at"``) and limiting.
- Convenience execution helpers: ``all()``, ``first()``, ``exists()``,
  ``count()``, ``values_list()``, and ``delete()``.

Filter Language
---------------
Keys are ``"<field>[__<lookup>]"``. Supported lookups:

- ``eq`` (default): equality comparison. ``None`` becomes ``IS NULL``.
- ``in`` / ``not_in``: membership checks (iterables normalized).
- ``lt`` / ``lte`` / ``gt`` / ``gte``: scalar comparisons.
- ``not``: inequality; ``None`` becomes ``IS NOT NULL``.

Examples
--------
Basic filtering and ordering:

>>> qb = QueryBuilder(User).filter(guild_id=123, name__not=None).order_by("-created_at")
>>> rows = await qb.all()

Negated filters and limits:

>>> first_row = await QueryBuilder(Guild).exclude(id__in=[1, 2, 3]).limit(1).first()

Value lists:

>>> ids = await QueryBuilder(User).filter(active=True).values_list("id", flat=True)

Counting / existence:

>>> exists = await QueryBuilder(User).filter(id=42).exists()
>>> total = await QueryBuilder(User).filter(active=True).count()

Notes
-----
- All execution helpers acquire a session via ``spooky.db.get_session()``.
- This helper does **not** manage transactions beyond a single statement.
- Only simple column lookups are supported; expressions/relationships are out of scope.
- For heavy/complex queries, use SQLAlchemy Core/ORM directly.

Raises
------
- ``TypeError`` when a provided field name is not a mapped column.
- ``ValueError`` when ``values_list`` is misused (e.g., ``flat=True`` with multiple fields).

"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from spooky.db import get_session
from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.elements import UnaryExpression

if TYPE_CHECKING:
    from spooky.models.base_models.base import Base

__all__ = [
    "Clause",
    "Ordering",
    "QueryBuilder",
]

# --- Public typing aliases ----------------------------------------------------

ModelT = TypeVar("ModelT", bound="Base")
Clause = ColumnElement[bool]
Ordering = UnaryExpression[Any] | ColumnElement[Any]


@lru_cache(maxsize=1)
def _get_session_factory() -> Callable[..., Any]:
    return get_session


# --- Internal helpers ---------------------------------------------------------


def _get_column(model: type[ModelT], name: str) -> InstrumentedAttribute[Any]:
    """Resolve a mapped column attribute on ``model`` by ``name``.

    Parameters
    ----------
    model:
        Declarative model class being queried.
    name:
        Attribute/column name to fetch.

    Returns
    -------
    InstrumentedAttribute[Any]
        The SQLAlchemy-mapped column attribute.

    Raises
    ------
    TypeError
        If the attribute does not exist or is not a mapped column.
    """
    column = getattr(model, name, None)
    if not isinstance(column, InstrumentedAttribute):
        raise TypeError(f"{model.__name__}.{name} is not a mapped column")
    return column


def _normalize_iterable(values: object) -> list[Any]:
    """Normalize a single value or iterable of values to a ``list[Any]``.

    Parameters
    ----------
    values:
        Either a scalar value or an iterable of values. Strings/bytes are
        treated as scalars (not iterables).

    Returns
    -------
    list[Any]
        A flat list of values suitable for ``IN``/``NOT IN`` filters.
    """
    if isinstance(values, (list, tuple, set)):
        return [cast(Any, item) for item in values]
    if isinstance(values, Iterable) and not isinstance(values, (str, bytes, bytearray)):
        return [cast(Any, item) for item in values]
    return [cast(Any, values)]


def _translate_filter(model: type[ModelT], key: str, value: Any, *, negate: bool = False) -> Clause:
    """Translate a ``field__lookup`` key and value into a SQLAlchemy boolean clause.

    Supported lookups (see module docstring): ``eq`` (default), ``in``, ``not_in``,
    ``lt``, ``lte``, ``gt``, ``gte``, ``not``.

    Parameters
    ----------
    model:
        Declarative model class being queried.
    key:
        ``"<field>[__<lookup>]"`` filter key.
    value:
        Value for the comparison operator.
    negate:
        If ``True``, apply boolean negation to the resulting expression.

    Returns
    -------
    Clause
        A SQLAlchemy boolean expression.

    Raises
    ------
    ValueError
        If the lookup is not supported.
    TypeError
        If ``field`` does not resolve to a mapped column.
    """
    field, _, lookup = key.partition("__")
    lookup = lookup or "eq"
    column = _get_column(model, field)

    if lookup == "eq":
        expr: Clause = column.is_(None) if value is None else column == value
    elif lookup == "in":
        expr = column.in_(_normalize_iterable(value))
    elif lookup == "not_in":
        expr = column.notin_(_normalize_iterable(value))
    elif lookup == "lt":
        expr = column < value
    elif lookup == "lte":
        expr = column <= value
    elif lookup == "gt":
        expr = column > value
    elif lookup == "gte":
        expr = column >= value
    elif lookup == "not":
        expr = column.isnot(None) if value is None else column != value
    else:
        raise ValueError(f"Unsupported lookup '{lookup}' for field '{field}'")

    return (~expr) if negate else expr


def _translate_filters(
    model: type[ModelT],
    filters: dict[str, Any],
    *,
    negate: bool = False,
) -> tuple[Clause, ...]:
    """Batch-translate a mapping of filter keys to clause expressions.

    Parameters
    ----------
    model:
        Declarative model class being queried.
    filters:
        Mapping of ``"<field>[__<lookup>]"`` to values.
    negate:
        If ``True``, each translated clause is negated.

    Returns
    -------
    tuple[Clause, ...]
        A tuple of SQLAlchemy boolean clauses.
    """
    return tuple(
        _translate_filter(model, key, value, negate=negate) for key, value in filters.items()
    )


# --- QueryBuilder -------------------------------------------------------------


@dataclass(slots=True)
class QueryBuilder(Generic[ModelT]):
    """Chainable async query helper for a specific mapped model.

    This class accumulates WHERE conditions, ORDER BY, and LIMIT, and can render
    a ``SELECT`` (or ``DELETE``) statement executed against the project's async
    session factory.

    Parameters
    ----------
    model:
        Declarative model class this builder targets.
    conditions:
        Initial WHERE-clause fragments (optional).
    orderings:
        Initial ORDER BY expressions (optional).
    limit:
        Optional row limit.

    Methods
    -------
    filter(**criteria):
        Add positive filters using the filter language.
    exclude(**criteria):
        Add negated filters (``NOT (...)``).
    order_by(*fields):
        Append ordering by field names; prefix with ``"-"`` for DESC.
    limit(value):
        Set a LIMIT.
    all():
        Execute and return a list of model instances.
    first():
        Execute and return the first model instance or ``None``.
    exists():
        Return ``True`` if at least one row matches.
    count():
        Return the count of matching rows.
    values_list(*fields, flat=False):
        Return raw tuples (or a flat list for one field).
    delete():
        Delete matching rows; returns number of affected rows.

    Notes
    -----
    - Builder instances are **immutable**; modifiers return new instances.
    - For complex joins/subqueries/aggregations, prefer SQLAlchemy directly.
    """

    model: type[ModelT]
    _conditions: tuple[Clause, ...]
    _orderings: tuple[Ordering, ...]
    _limit: int | None

    def __init__(
        self,
        model: type[ModelT],
        *,
        conditions: Sequence[Clause] | None = None,
        orderings: Sequence[Ordering] | None = None,
        limit: int | None = None,
    ) -> None:
        self.model = model
        self._conditions = tuple(conditions or ())
        self._orderings = tuple(orderings or ())
        self._limit = limit

    # --- Query modifiers -------------------------------------------------

    def filter(self, **criteria: Any) -> QueryBuilder[ModelT]:
        """Return a new builder with additional positive filters.

        Examples
        --------
        >>> QueryBuilder(User).filter(id=1, name__not=None)
        """
        new_conditions = self._conditions + _translate_filters(self.model, criteria)
        return QueryBuilder(
            self.model, conditions=new_conditions, orderings=self._orderings, limit=self._limit
        )

    def exclude(self, **criteria: Any) -> QueryBuilder[ModelT]:
        """Return a new builder with additional **negated** filters.

        Examples
        --------
        >>> QueryBuilder(User).exclude(id__in=[1, 2, 3])
        """
        new_conditions = self._conditions + _translate_filters(self.model, criteria, negate=True)
        return QueryBuilder(
            self.model, conditions=new_conditions, orderings=self._orderings, limit=self._limit
        )

    def order_by(self, *fields: str) -> QueryBuilder[ModelT]:
        """Return a new builder with extra ORDER BY expressions.

        Parameters
        ----------
        fields:
            Field names to sort by. Prefix with ``"-"`` for descending.

        Examples
        --------
        >>> QueryBuilder(User).order_by("name", "-created_at")
        """
        ordered: list[Ordering] = list(self._orderings)
        for field in fields:
            descending = field.startswith("-")
            name = field[1:] if descending else field
            column = _get_column(self.model, name)
            ordered.append(column.desc() if descending else column.asc())
        return QueryBuilder(
            self.model, conditions=self._conditions, orderings=tuple(ordered), limit=self._limit
        )

    def limit(self, value: int) -> QueryBuilder[ModelT]:
        """Return a new builder with ``LIMIT value`` applied."""
        return QueryBuilder(
            self.model, conditions=self._conditions, orderings=self._orderings, limit=value
        )

    # --- Execution helpers -----------------------------------------------

    def where_clause(self) -> Clause | None:
        """Combine accumulated conditions into a single Clause (or ``None``)."""
        if not self._conditions:
            return None
        if len(self._conditions) == 1:
            return self._conditions[0]
        return and_(*self._conditions)

    def _build_select(self, *columns: Any) -> Select[Any]:
        """Render a ``SELECT`` statement with current WHERE/ORDER/LIMIT."""
        stmt = select(*(columns or (self.model,)))
        where = self.where_clause()
        if where is not None:
            stmt = stmt.where(where)
        if self._orderings:
            stmt = stmt.order_by(*self._orderings)
        if self._limit is not None:
            stmt = stmt.limit(self._limit)
        return stmt

    async def all(self) -> list[ModelT]:
        """Execute the SELECT and return all resulting model instances."""
        get_session = _get_session_factory()
        async with get_session() as session:
            result = await session.scalars(self._build_select())
            return list(result)

    async def first(self) -> ModelT | None:
        """Execute the SELECT with ``LIMIT 1`` and return the first row or ``None``."""
        limited = self.limit(1)
        get_session = _get_session_factory()
        async with get_session() as session:
            result = await session.scalars(limited._build_select())
            return result.first()

    async def exists(self) -> bool:
        """Return ``True`` if at least one row matches the current filters."""
        return (await self.first()) is not None

    async def count(self) -> int:
        """Return the COUNT(*) for rows matching the current filters."""
        get_session = _get_session_factory()
        async with get_session() as session:
            stmt = select(func.count()).select_from(self.model)
            where = self.where_clause()
            if where is not None:
                stmt = stmt.where(where)
            value = await session.scalar(stmt)
            return int(value or 0)

    async def values_list(self, *fields: str, flat: bool = False) -> list[Any]:
        """Return raw tuples (or a flat list for single-field queries).

        Parameters
        ----------
        fields:
            One or more field names to project.
        flat:
            If ``True``, requires **exactly one** field and returns a flat list.

        Returns
        -------
        list[Any]
            A flat list when ``flat=True`` with one field; otherwise a list of
            tuples (single-field tuples when ``flat=False``).

        Raises
        ------
        ValueError
            - If no fields are provided.
            - If ``flat=True`` but more than one field is requested.
        TypeError
            If any field is not a mapped column.
        """
        if not fields:
            raise ValueError("values_list expects at least one field name")
        columns = [_get_column(self.model, name) for name in fields]
        get_session = _get_session_factory()
        async with get_session() as session:
            result = await session.execute(self._build_select(*columns))
            rows = result.all()
            if flat:
                if len(columns) != 1:
                    raise ValueError("flat=True is only valid when a single field is requested")
                return [row[0] for row in rows]
            if len(columns) == 1:
                return [(row[0],) for row in rows]
            return [tuple(row) for row in rows]

    async def delete(self) -> int:
        """Delete rows matching the current filters and return affected count.

        Notes
        -----
        - This issues a single ``DELETE FROM <table> WHERE ...`` statement.
        - Transaction/commit behavior is managed by the session context.
        """
        get_session = _get_session_factory()
        async with get_session() as session:
            stmt = delete(self.model)
            where = self.where_clause()
            if where is not None:
                stmt = stmt.where(where)
            result = await session.execute(stmt)
            count = getattr(result, "rowcount", None)
            return int(count or 0)
