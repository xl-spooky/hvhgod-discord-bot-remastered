"""ORM model representing a persisted Discord guild entity.

This module defines :class:`Guild`, a database-backed representation of a
Discord guild (server) identified by its unique snowflake ID. It subclasses
:class:`~spooky.models.base_models.base.DiscordEntity`, inheriting a shared
primary key structure and requiring a ``fetch`` method that can resolve the
instance into an active Disnake guild object.

Purpose
-------
- Used as a durable reference for guild-related features (e.g., settings,
  configuration, logging, permissions).
- Enables relational mapping across user or feature tables.
- Serves as a foundational entity for per-guild DB hydration logic.

Notes
-----
- ``fetch()`` uses only the bots internal cache and does not issue REST
  requests. For broader resolution (with fallback to REST + caching +
  DB hydration), use :func:`spooky.models.cache.ensure_guild`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import disnake
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import DiscordEntity

if TYPE_CHECKING:
    from spooky.bot import Spooky


class Guild(DiscordEntity):
    """Represent a Discord guild (server) stored by its snowflake ID.

    Attributes
    ----------
    id: int
        The Discord guild snowflake, inherited from ``DiscordEntity``.

    Methods
    -------
    fetch(bot):
        Resolve this guild into a live ``disnake.Guild`` from cache.

    Examples
    --------
    >>> guild = await Guild.create(id=987654321098765432)
    >>> live = await guild.fetch(bot)
    >>> if live:
    ...     print(live.name)
    """

    __tablename__ = "guild"

    prefix: Mapped[str | None] = mapped_column(String(2), nullable=True)

    async def fetch(self, bot: Spooky) -> disnake.Guild | None:
        """Return the corresponding ``disnake.Guild`` from client cache.

        Parameters
        ----------
        bot:
            The active :class:`~spooky.bot.Spooky` instance, providing access
            to the Disnake client's in-memory guild cache.

        Returns
        -------
        disnake.Guild | None
            The cached guild object if available; otherwise ``None``.

        Notes
        -----
        - This does **not** attempt REST-based resolution.
        - Use :func:`spooky.models.cache.ensure_guild` for DB hydration and
          cache+REST resolution.
        """
        return bot.get_guild(int(self.id))
