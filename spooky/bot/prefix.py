"""Prefix resolution utilities for the private bot runtime."""

from __future__ import annotations

import disnake
from spooky.models.utils import fetch_db_guild, fetch_db_user

DEFAULT_PREFIX = ","
MAX_PREFIX_LENGTH = 2


def sanitize_prefix(prefix: str) -> str:
    """Validate and normalize a prefix string."""
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
    """Return the active prefixes for a message (user > guild > default)."""
    prefixes: list[str] = []

    author_id = getattr(message.author, "id", None)
    if author_id is not None:
        user = await fetch_db_user(int(author_id))
        if user and user.prefix:
            prefixes.append(sanitize_prefix(user.prefix))

    guild_id = getattr(getattr(message, "guild", None), "id", None)
    has_guild_override = False
    if guild_id is not None:
        guild = await fetch_db_guild(int(guild_id))
        if guild and guild.prefix:
            guild_prefix = sanitize_prefix(guild.prefix)
            if guild_prefix not in prefixes:
                prefixes.append(guild_prefix)
            has_guild_override = True

    if not has_guild_override and default not in prefixes:
        prefixes.append(default)
    return prefixes


async def refresh_guild_prefix(guild_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """No-op in private mode (no prefix cache)."""


async def refresh_user_prefix(user_id: int, *, default: str = DEFAULT_PREFIX) -> None:
    """No-op in private mode (no prefix cache)."""


def invalidate_prefix_cache() -> None:
    """No-op in private mode (no prefix cache)."""


__all__ = [
    "DEFAULT_PREFIX",
    "MAX_PREFIX_LENGTH",
    "get_effective_prefix",
    "invalidate_prefix_cache",
    "refresh_guild_prefix",
    "refresh_user_prefix",
    "sanitize_prefix",
]
