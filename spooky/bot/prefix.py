"""Prefix resolution and caching utilities for the Spooky bot.

This module implements a lightweight, Redis-backed prefix system that lets
:class:`~spooky.bot.Spooky` behave as a *hybrid* command bot—supporting both
traditional **prefix-based** commands and **slash** commands—while keeping a
single source of truth for prefix reads, sanitization, and cache invalidation.

Key features
------------
- **Central snapshot cache** backed by :class:`~spooky.models.cache.TTLCache`
  (Redis). The cache holds exactly one key (``"snapshot"``) that stores a
  :class:`PrefixSnapshot` containing user and guild override maps.
- **Lazy population** of user/guild prefixes via existing DB helpers
  (``fetch_db_user`` / ``fetch_db_guild``). Cache hits avoid database work.
- **Strict sanitization**: trimmed, printable, and limited to
  :data:`MAX_PREFIX_LENGTH` characters (default: 2).
- **Explicit refresh & invalidation** helpers to keep the snapshot coherent
  immediately after writes, or when external changes have happened.

Integration
-----------
Call :func:`get_effective_prefix` from your bot's ``get_prefix`` override.
It resolves precedence **user > guild > default** and returns the ordered list
of prefixes that should trigger prefix-based commands.

Examples
--------
>>> async def get_prefix(bot, message):
...     from spooky.ext.prefix import get_effective_prefix
...     return await get_effective_prefix(message)

"""

from __future__ import annotations

from dataclasses import dataclass, field

import disnake
from loguru import logger
from spooky.models.cache import TTLCache
from spooky.models.utils import fetch_db_guild, fetch_db_user

DEFAULT_PREFIX = ","
"""Default prefix used when neither a guild nor a user override exists."""

MAX_PREFIX_LENGTH = 2
"""Maximum number of characters allowed for custom prefixes."""

_CACHE_KEY = "snapshot"
_CACHE_TTL_SECONDS = 900.0


@dataclass(slots=True)
class PrefixSnapshot:
    """Container stored inside the prefix cache.

    Attributes
    ----------
    default : str
        Global fallback prefix. Kept on the snapshot for future extensibility.
    guild_prefixes : dict[int, str | None]
        Mapping of guild IDs to their **sanitized** prefix. ``None`` is cached
        to denote "no override" and to prevent repeated DB lookups.
    user_prefixes : dict[int, str | None]
        Mapping of user IDs to their **sanitized** prefix. ``None`` mirrors the
        absence of an override.
    """

    default: str = DEFAULT_PREFIX
    guild_prefixes: dict[int, str | None] = field(default_factory=dict)
    user_prefixes: dict[int, str | None] = field(default_factory=dict)


_prefix_cache = TTLCache[str, PrefixSnapshot](
    name="prefix",
    default_ttl=_CACHE_TTL_SECONDS,
    maxsize=1,
    redis_prefix="spooky:cache:prefix",
)


def sanitize_prefix(prefix: str) -> str:
    """Validate and normalise a prefix string.

    The result is trimmed, restricted to printable characters, and constrained
    to a maximum length of :data:`MAX_PREFIX_LENGTH`.

    Parameters
    ----------
    prefix : str
        Raw prefix provided by the caller.

    Returns
    -------
    str
        The sanitized prefix.

    Raises
    ------
    ValueError
        If the prefix becomes empty after trimming, exceeds
        :data:`MAX_PREFIX_LENGTH`, or contains whitespace/non-printable characters.

    Examples
    --------
    >>> sanitize_prefix("  ab ")
    'ab'
    >>> sanitize_prefix("!!")
    '!!'
    """
    trimmed = prefix.strip()
    if not trimmed:
        raise ValueError("Prefix cannot be empty or whitespace only.")
    if len(trimmed) > MAX_PREFIX_LENGTH:
        raise ValueError(f"Prefix must be at most {MAX_PREFIX_LENGTH} characters long.")
    if any(char.isspace() for char in trimmed):
        raise ValueError("Prefix cannot contain whitespace characters.")
    if not all(char.isprintable() for char in trimmed):
        raise ValueError("Prefix must contain printable characters.")
    return trimmed


async def get_effective_prefix(
    message: disnake.Message, *, default: str = DEFAULT_PREFIX
) -> list[str]:
    """Return the prefixes that should apply to ``message``.

    Resolution order is **user override**, **guild override**, then the
    **global default**. Each miss populates the Redis-backed snapshot so
    subsequent calls avoid extra database queries. All applicable prefixes are
    returned so message commands remain invokable via user, guild, or default
    overrides simultaneously.

    Parameters
    ----------
    message : disnake.Message
        The incoming Discord message used to determine user/guild context.
    default : str, optional
        The global default prefix if no overrides apply. Defaults to
        :data:`DEFAULT_PREFIX`.

    Returns
    -------
    list[str]
        Ordered list of prefixes that should trigger message commands. The
        default prefix is included unless a guild-specific override is active.

    Notes
    -----
    - This function is safe to call on DMs (no guild). In that case,
      only the user override and fallback default are considered.
    - Snapshot updates are persisted back to the cache on each mutation,
      keeping a single consistent source of truth.
    """
    snapshot = await _get_snapshot(default)

    prefixes: list[str] = []
    has_guild_override = False

    author_id = getattr(message.author, "id", None)
    if author_id is not None:
        user_prefix = await _ensure_user_prefix(snapshot, int(author_id))
        if user_prefix:
            prefixes.append(user_prefix)

    guild_id = getattr(getattr(message, "guild", None), "id", None)
    if guild_id is not None:
        guild_prefix = await _ensure_guild_prefix(snapshot, int(guild_id))
        if guild_prefix and guild_prefix not in prefixes:
            prefixes.append(guild_prefix)
            has_guild_override = True

    default_prefix = snapshot.default
    if not has_guild_override and default_prefix not in prefixes:
        prefixes.append(default_prefix)

    return prefixes


async def refresh_guild_prefix(guild_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """Reload and cache the guild prefix for ``guild_id``.

    Use this right after you update the guild's prefix in the database to keep
    the cache coherent.

    Parameters
    ----------
    guild_id : int
        Target guild ID whose prefix should be refreshed from the DB.
    default : str, optional
        Default prefix to synchronize onto the snapshot if it changed.
    """
    snapshot = await _get_snapshot(default)
    await _ensure_guild_prefix(snapshot, guild_id, force_reload=True)


async def refresh_user_prefix(user_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """Reload and cache the user prefix for ``user_id``.

    Use this right after you update the user's prefix in the database.

    Parameters
    ----------
    user_id : int
        Target user ID whose prefix should be refreshed from the DB.
    default : str, optional
        Default prefix to synchronize onto the snapshot if it changed.
    """
    snapshot = await _get_snapshot(default)
    await _ensure_user_prefix(snapshot, user_id, force_reload=True)


def invalidate_prefix_cache() -> None:
    """Completely clear the prefix cache.

    This removes the single snapshot entry (``"snapshot"``). The next request
    re-creates an empty :class:`PrefixSnapshot`.
    """
    _prefix_cache.invalidate(_CACHE_KEY)


async def _get_snapshot(default: str) -> PrefixSnapshot:
    """Fetch or create the cached :class:`PrefixSnapshot` and sync ``default``."""
    cached = await _prefix_cache.get(_CACHE_KEY)
    if cached is not None:
        if cached.default != default:
            cached.default = default
            await _prefix_cache.set(_CACHE_KEY, cached)
        return cached
    snapshot = PrefixSnapshot(default=default)
    await _prefix_cache.set(_CACHE_KEY, snapshot)
    return snapshot


async def _ensure_guild_prefix(
    snapshot: PrefixSnapshot,
    guild_id: int,
    *,
    force_reload: bool = False,
) -> str | None:
    """Ensure a guild prefix is present in the snapshot; optionally reload."""
    if not force_reload and guild_id in snapshot.guild_prefixes:
        return snapshot.guild_prefixes[guild_id]

    try:
        guild = await fetch_db_guild(guild_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Failed to fetch guild {} for prefix lookup: {}", guild_id, exc)
        return snapshot.guild_prefixes.get(guild_id)

    value = guild.prefix
    sanitized = _sanitize_optional(value)
    snapshot.guild_prefixes[guild_id] = sanitized
    await _prefix_cache.set(_CACHE_KEY, snapshot)
    return sanitized


async def _ensure_user_prefix(
    snapshot: PrefixSnapshot,
    user_id: int,
    *,
    force_reload: bool = False,
) -> str | None:
    """Ensure a user prefix is present in the snapshot; optionally reload."""
    if not force_reload and user_id in snapshot.user_prefixes:
        return snapshot.user_prefixes[user_id]

    try:
        user = await fetch_db_user(user_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Failed to fetch user {} for prefix lookup: {}", user_id, exc)
        return snapshot.user_prefixes.get(user_id)

    value = user.prefix
    sanitized = _sanitize_optional(value)
    snapshot.user_prefixes[user_id] = sanitized
    await _prefix_cache.set(_CACHE_KEY, snapshot)
    return sanitized


def _sanitize_optional(value: str | None) -> str | None:
    """Sanitize an optional prefix; invalid or empty values become ``None``."""
    if value is None:
        return None
    try:
        return sanitize_prefix(value)
    except ValueError as exc:
        logger.debug("Discarding invalid cached prefix %r: {}", value, exc)
        return None


async def invalidate_guild_prefix(guild_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """Remove the cached guild prefix so it will be reloaded on next access.

    Parameters
    ----------
    guild_id : int
        The guild whose cached prefix should be invalidated.
    default : str, optional
        Default prefix to synchronize onto the snapshot if it changed.
    """
    snapshot = await _get_snapshot(default)
    if guild_id in snapshot.guild_prefixes:
        snapshot.guild_prefixes.pop(guild_id, None)
        await _prefix_cache.set(_CACHE_KEY, snapshot)


async def invalidate_user_prefix(user_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """Remove the cached user prefix so it will be reloaded on next access.

    Parameters
    ----------
    user_id : int
        The user whose cached prefix should be invalidated.
    default : str, optional
        Default prefix to synchronize onto the snapshot if it changed.
    """
    snapshot = await _get_snapshot(default)
    if user_id in snapshot.user_prefixes:
        snapshot.user_prefixes.pop(user_id, None)
        await _prefix_cache.set(_CACHE_KEY, snapshot)


__all__ = [
    "DEFAULT_PREFIX",
    "get_effective_prefix",
    "invalidate_guild_prefix",
    "invalidate_prefix_cache",
    "invalidate_user_prefix",
    "refresh_guild_prefix",
    "refresh_user_prefix",
    "sanitize_prefix",
]
