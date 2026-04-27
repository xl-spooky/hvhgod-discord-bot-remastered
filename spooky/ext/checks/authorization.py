"""Authorization helpers for bot configuration flows."""

from __future__ import annotations

import disnake
from spooky.bot import Spooky
from spooky.ext.db import fetch_bool_flag
from spooky.models import (
    AuthorizationAccess,
    GuildBotAuthorizationAccess,
    GuildBotConfigureAuthorization,
    ensure_member,
)

__all__ = ["AuthorizationAccess", "is_owner_or_authorized_for_access"]


async def is_owner_or_authorized_for_access(
    bot: Spooky,
    guild_id: int,
    user: disnake.User | disnake.Member,
    access: AuthorizationAccess,
) -> bool:
    """Return ``True`` when ``user`` may manage the given ``access`` scope.

    The helper resolves ``user`` to a :class:`disnake.Member` for ``guild_id``
    and checks whether the member is the guild owner or authorized for bot
    configuration. Authorized members must also have the requested ``access``
    enabled. Missing toggle rows default to ``True`` to preserve
    backward-compatible behavior.
    """
    if isinstance(user, disnake.Member) and user.guild and user.guild.id == guild_id:
        member: disnake.Member | None = user
    else:
        member = await ensure_member(bot, guild_id, user.id)

    if member is None:
        return False

    owner_id = getattr(member.guild, "owner_id", None)
    if owner_id is not None and int(owner_id) == int(member.id):
        return True

    is_authorized = await GuildBotConfigureAuthorization.filter(
        guild_id=int(guild_id), user_id=int(member.id)
    ).exists()
    if not is_authorized:
        return False

    return await fetch_bool_flag(
        GuildBotAuthorizationAccess.filter(guild_id=int(guild_id), access=access),
        field="allowed",
        default=True,
    )
