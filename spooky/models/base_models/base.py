"""Core SQLAlchemy base classes for all Spooky ORM models.

This module defines two foundational classes for all Spooky database models:

1. :class:`Base` - A declarative base extending SQLAlchemys ``DeclarativeBase``,
   equipped with convenience helpers for query construction and object creation.

2. :class:`DiscordEntity` - An abstract mixin representing models that correspond
   directly to persistent Discord objects (e.g., users or guilds), identified by
   their numeric snowflake IDs.

Key Features
------------
- Built-in `query()`, `filter()`, and `create()` helpers using
  :class:`~spooky.models.query.QueryBuilder`.
- Standardized ``id`` column for Discord-based models, using BigInteger PKs.
- Optional ``fetch()`` implementation hook for resolving a model to a live
  Discord object via the provided bot instance.

Examples
--------
Fetch all Guild records:

>>> from spooky.models import Guild
>>> guilds = await Guild.all().all()

Create a new model row:

>>> user = await User.create(id=123456789012345678)

Chain filters:

>>> active_users = await User.filter(active=True).all()

Subclassing for Discord entities:

>>> class MyEntity(DiscordEntity):
...     async def fetch(self, bot: Spooky):
...         return bot.get_channel(self.id)

Notes
-----
- ``create()`` flushes the new record but does not commit the broader
  transaction unless the session is committed externally.
- ``DiscordEntity.fetch()`` must be implemented by concrete subclasses.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar

import disnake
from spooky.db import get_session
from spooky.models.query import QueryBuilder
from sqlalchemy import BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

if TYPE_CHECKING:
    from spooky.bot import Spooky

ModelT = TypeVar("ModelT", bound="Base")


@lru_cache(maxsize=1)
def _get_session_factory() -> Callable[..., Any]:
    return get_session


class Base(DeclarativeBase):
    """Declarative SQLAlchemy base with convenience query and creation helpers.

    Methods
    -------
    query():
        Return a new :class:`QueryBuilder` for this model class.
    all():
        Alias of ``query()`` for fluency (e.g., ``Model.all().filter(...)``).
    filter(**criteria):
        Apply filter criteria using the QueryBuilder DSL.
    create(**payload):
        Insert a new database row using ``payload`` as constructor kwargs.

    Examples
    --------
    >>> await User.create(id=1, name="Spooky")
    >>> results = await User.filter(name__not=None).all()
    """

    __abstract__ = True

    @classmethod
    def query(cls: type[ModelT]) -> QueryBuilder[ModelT]:
        """Return a :class:`QueryBuilder` bound to this model."""
        return QueryBuilder(cls)

    @classmethod
    def all(cls: type[ModelT]) -> QueryBuilder[ModelT]:
        """Return a :class:`QueryBuilder` with no filters applied."""
        return QueryBuilder(cls)

    @classmethod
    def filter(cls: type[ModelT], **criteria: Any) -> QueryBuilder[ModelT]:
        """Return a new query filtered using QueryBuilder syntax."""
        return QueryBuilder(cls).filter(**criteria)

    @classmethod
    async def create(cls: type[ModelT], **payload: Any) -> ModelT:
        """Create and flush a new instance of the model.

        Parameters
        ----------
        **payload:
            Keyword arguments passed into the model initializer.

        Returns
        -------
        ModelT
            The newly created instance (now part of the session).

        Notes
        -----
        - A database flush is performed, but final commit depends on the
          session manager or upstream transaction wrapper.
        """
        get_session = _get_session_factory()
        instance = cls(**payload)
        async with get_session() as session:
            session.add(instance)
            await session.flush()
        return instance


class DiscordEntity(Base):
    """Base model for persisted Discord snowflake objects.

    Attributes
    ----------
    id:
        Discord snowflake ID, used as the primary key. Autoincrement is disabled
        since Discord IDs are pre-generated.

    Methods
    -------
    fetch(bot):
        Resolve this persisted entity into a live Discord object (abstract).

    Notes
    -----
    - Must be subclassed to implement :meth:`fetch`.
    - Intended for models mirroring Discord resources (e.g., Users, Guilds).
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    async def fetch(self, bot: Spooky) -> disnake.abc.Snowflake | None:
        """Resolve this record into a live Discord object using the bot.

        Parameters
        ----------
        bot:
            The running :class:`~spooky.bot.Spooky` instance used to access
            cached or REST-fetched Discord data.

        Returns
        -------
        disnake.abc.Snowflake | None
            The resolved Discord object, or ``None`` if unavailable.

        Raises
        ------
        NotImplementedError
            If not overridden by a concrete subclass.
        """
        raise NotImplementedError
