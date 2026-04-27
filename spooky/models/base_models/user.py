"""ORM model representing a persisted Discord user entity.

This module defines :class:`User`, a database-backed representation of a
Discord user identified by its unique snowflake ID. It extends
:class:`~spooky.models.base_models.base.DiscordEntity`, inheriting the
standard ``id`` primary key and requiring a ``fetch`` method
implementation for resolution into a live `disnake.User`.

Purpose
-------
- Tracks users that have interacted with the bot or are otherwise relevant
  to database-backed features (e.g., economy, permissions, snipe logs).
- Provides a stable reference for foreign keys elsewhere in the schema.

Notes
-----
- ``fetch()`` resolves only from local bot cache and does not hit REST.
  Use utilities such as ``ensure_user()`` from ``spooky.models.cache`` to
  perform cached+REST resolution plus DB hydration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import disnake
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import DiscordEntity

if TYPE_CHECKING:
    from spooky.bot import Spooky


class User(DiscordEntity):
    """Represent a Discord user entity using its snowflake ID.

    Attributes
    ----------
    id: int
        The Discord user snowflake, inherited from ``DiscordEntity``.

    Methods
    -------
    fetch(bot):
        Return the corresponding ``disnake.User`` if available in cache.

    Examples
    --------
    >>> user = await User.create(id=123456789012345678)
    >>> live_user = await user.fetch(bot)
    >>> if live_user:
    ...     print(live_user.name)
    """

    __tablename__ = "user"

    prefix: Mapped[str | None] = mapped_column(String(2), nullable=True)

    async def fetch(self, bot: Spooky) -> disnake.User | None:
        """Resolve this user to a live ``disnake.User`` via the bot cache.

        Parameters
        ----------
        bot:
            Active :class:`~spooky.bot.Spooky` instance used to access
            the internal Disnake client/user cache.

        Returns
        -------
        disnake.User | None
            The user object if present in the client cache; otherwise ``None``.

        Notes
        -----
        - This method does **not** attempt any REST requests.
        - For DB+REST resolution, favor :func:`spooky.models.cache.ensure_user`.
        """
        return bot.get_user(int(self.id))
