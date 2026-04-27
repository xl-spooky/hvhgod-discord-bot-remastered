"""Guild ownership checks."""

from __future__ import annotations

import disnake
from spooky.bot import Spooky
from spooky.models import ensure_member

__all__ = ["is_guild_owner"]


async def is_guild_owner(
    bot: Spooky,
    guild_id: int,
    user: disnake.User | disnake.Member,
) -> bool:
    """Return ``True`` if ``user`` owns ``guild_id``.

    The check resolves the invoking user to a :class:`disnake.Member` for the
    target guild, falling back to :func:`spooky.models.ensure_member` when
    necessary. ``False`` is returned when the member cannot be resolved or when
    the guild owner ID is unavailable.
    """
    if isinstance(user, disnake.Member) and user.guild and user.guild.id == guild_id:
        member: disnake.Member | None = user
    else:
        member = await ensure_member(bot, guild_id, user.id)

    if member is None:
        return False

    owner_id = member.guild.owner_id
    return owner_id is not None and owner_id == member.id
