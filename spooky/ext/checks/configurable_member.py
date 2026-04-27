"""Reusable check helpers for configuration target validation."""

from __future__ import annotations

from dataclasses import dataclass

import disnake
from spooky.bot import Spooky
from spooky.models import ensure_member

__all__ = ["ConfigurableMemberCheck", "validate_configurable_member"]


@dataclass(slots=True)
class ConfigurableMemberCheck:
    """Result from validating whether a user can be configured."""

    allowed: bool
    reason: str | None
    member: disnake.Member | None

    @classmethod
    def success(cls, member: disnake.Member) -> ConfigurableMemberCheck:
        return cls(True, None, member)

    @classmethod
    def failure(cls, reason: str) -> ConfigurableMemberCheck:
        return cls(False, reason, None)


async def validate_configurable_member(
    bot: Spooky, guild_id: int, user: disnake.User | disnake.Member
) -> ConfigurableMemberCheck:
    """Ensure ``user`` is a non-bot, non-owner member of ``guild_id``."""
    if getattr(user, "bot", False):
        return ConfigurableMemberCheck.failure("Bots cannot be configured here.")

    if isinstance(user, disnake.Member) and user.guild and user.guild.id == guild_id:
        member: disnake.Member | None = user
    else:
        member = await ensure_member(bot, guild_id, user.id)

    if member is None:
        return ConfigurableMemberCheck.failure("User not found in this guild.")

    owner_id = getattr(member.guild, "owner_id", None)
    if owner_id is not None and int(owner_id) == int(member.id):
        return ConfigurableMemberCheck.failure("The guild owner cannot be configured here.")

    return ConfigurableMemberCheck.success(member)
