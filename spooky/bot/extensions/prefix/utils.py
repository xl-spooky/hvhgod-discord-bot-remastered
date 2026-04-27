"""Utility helpers for prefix commands.

This module provides convenience functions used by the
:mod:`spooky.bot.extensions.prefix` command handlers.

Overview
--------
These helpers encapsulate common operations such as:
- Ensuring user/guild records exist for prefix storage.
- Fetching prefix overrides without side effects.
- Validating or sanitizing prefix strings.
- Building a compact embed summarizing prefix status.

Design notes
------------
- ``ensure_*`` functions are **idempotent**: they query the row and create it
  only if absent, returning the ORM object in either case.
- Prefix validation uses the same canonical logic as the global prefix manager
  (:func:`spooky.bot.prefix.sanitize_prefix`).
- Fetch helpers use the lightweight :class:`~spooky.models.query.QueryBuilder`
  abstraction to minimize session boilerplate.
- ``build_status_embed`` creates a uniform representation used by both message
  and slash-based prefix viewers.
"""

from __future__ import annotations

import disnake
from spooky.bot.prefix import sanitize_prefix
from spooky.models.base_models.guild import Guild
from spooky.models.base_models.user import User
from spooky.models.query import QueryBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "build_status_embed",
    "ensure_guild",
    "ensure_user",
    "fetch_guild_prefix",
    "fetch_user_prefix",
    "sanitize_override",
]


async def ensure_user(session: AsyncSession, user_id: int) -> User:
    """Fetch or create a user row for prefix operations.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy session bound to the current transaction context.
    user_id : int
        Discord user ID to query or create.

    Returns
    -------
    User
        The persistent :class:`~spooky.models.base_models.user.User` ORM instance,
        newly inserted if it did not exist.

    Notes
    -----
    The function commits **no transaction**; the caller is responsible for
    session lifecycle management.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=user_id)
        session.add(user)
        await session.flush()
    return user


async def ensure_guild(session: AsyncSession, guild_id: int) -> Guild:
    """Fetch or create a guild row for prefix operations.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy session bound to the current transaction context.
    guild_id : int
        Discord guild ID to query or create.

    Returns
    -------
    Guild
        The persistent :class:`~spooky.models.base_models.guild.Guild` ORM instance,
        newly inserted if it did not exist.

    Notes
    -----
    The function performs no commit; the caller is responsible for transaction
    finalization.
    """
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    if guild is None:
        guild = Guild(id=guild_id)
        session.add(guild)
        await session.flush()
    return guild


def sanitize_override(
    prefix: str | None,
    *,
    default: str,
    allow_default: bool = False,
) -> str | None:
    """Validate and normalize a prefix override.

    Parameters
    ----------
    prefix : str | None
        Raw input string provided by the user. May be ``None`` or empty.
    default : str
        Default prefix for comparison; values equal to this may be treated as
        ``None`` depending on ``allow_default``.
    allow_default : bool, optional
        When ``True``, retain prefixes that match ``default`` instead of
        normalizing them to ``None``.

    Returns
    -------
    str | None
        Normalized prefix if valid and distinct from the default, otherwise ``None``.

    Raises
    ------
    ValueError
        If the prefix fails validation (too long, contains invalid characters, etc.).

    Notes
    -----
    - Relies on :func:`spooky.bot.prefix.sanitize_prefix` for canonical validation.
    - This ensures callers can optionally retain default-equivalent prefixes when
      they need to override an intermediate layer (e.g., guild overrides).
    """
    if prefix is None:
        return None

    sanitized = sanitize_prefix(prefix)
    if sanitized == default and not allow_default:
        return None
    return sanitized


async def fetch_user_prefix(user_id: int) -> str | None:
    """Return the stored prefix override for ``user_id`` without creating a row.

    Parameters
    ----------
    user_id : int
        Discord user ID whose prefix override should be retrieved.

    Returns
    -------
    str | None
        The user's prefix override, or ``None`` if not set or user row is absent.

    Notes
    -----
    This helper performs a single lightweight SELECT via :class:`QueryBuilder`
    and does **not** create missing rows.
    """
    user = await QueryBuilder(User).filter(id=user_id).first()
    return user.prefix if user else None


async def fetch_guild_prefix(guild_id: int) -> str | None:
    """Return the stored prefix override for ``guild_id`` without creating a row.

    Parameters
    ----------
    guild_id : int
        Discord guild ID whose prefix override should be retrieved.

    Returns
    -------
    str | None
        The guild's prefix override, or ``None`` if not set or guild row is absent.

    Notes
    -----
    Like :func:`fetch_user_prefix`, this avoids implicit creation of new rows.
    """
    guild = await QueryBuilder(Guild).filter(id=guild_id).first()
    return guild.prefix if guild else None


def build_status_embed(
    *,
    default_prefix: str,
    user_prefix: str | None,
    guild_prefix: str | None,
    guild_name: str,
) -> disnake.Embed:
    """Construct an informative embed summarizing prefix overrides.

    Parameters
    ----------
    default_prefix : str
        Global default prefix configured for the bot.
    user_prefix : str | None
        User-level override if defined.
    guild_prefix : str | None
        Guild-level override if defined.
    guild_name : str
        Display name of the guild (or "Direct Message" for DMs).

    Returns
    -------
    disnake.Embed
        A neutral, non-colored embed listing each relevant prefix layer.

    Notes
    -----
    - Field visibility adapts automatically to context: DM vs guild.
    """
    embed = disnake.Embed(title="Prefix status")
    if guild_name == "Direct Message":
        embed.add_field(name="Default", value=f"`{default_prefix}`", inline=False)
    if guild_name != "Direct Message":
        guild_value = "Not set" if guild_prefix is None else f"`{guild_prefix}`"
        embed.add_field(
            name=f"Guild override ({guild_name})",
            value=guild_value,
            inline=False,
        )

    user_value = "Not set" if user_prefix is None else f"`{user_prefix}`"
    embed.add_field(name="User override", value=user_value, inline=False)
    return embed
