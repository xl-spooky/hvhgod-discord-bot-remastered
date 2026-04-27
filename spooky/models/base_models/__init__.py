"""Base Discord-related models grouped for structured, semantic organization.

This subpackage aggregates foundational ORM models that represent **core
Discord entities** as stored in the database:

- :class:`DiscordEntity` - A mixin providing a common structure for Discord
  snowflake-based models.
- :class:`Guild` - Represents a Discord guild (server) tracked by the bot.
- :class:`User` - Represents a Discord user; hydrated alongside caching logic.

Purpose
-------
This module provides clean, explicit re-exports for common base models, enabling:
- Predictable imports (e.g., ``from spooky.models.base_models import User``),
- Easier auto-completion and documentation navigation,
- A stable, top-level API without needing to reference deep file paths.

Notes
-----
- Only stable, high-level models should be re-exported here.
- Internal mixins or future subtypes should remain in their respective files
  unless they are part of the public model API.

Examples
--------
>>> from spooky.models.base_models import Guild
>>> guild = await fetch_db_guild(123456789012345678)

>>> from spooky.models.base_models import User
>>> print(User.__tablename__)
"""

from __future__ import annotations

from .base import DiscordEntity
from .guild import Guild
from .user import User

__all__ = ["DiscordEntity", "Guild", "User"]
