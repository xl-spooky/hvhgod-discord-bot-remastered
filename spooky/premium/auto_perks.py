"""Helpers to reconcile auto-nuke perks when premium changes."""

from __future__ import annotations

from spooky.bot import Spooky
from spooky.bot.extensions.settings.guild.containers.auto.state import FREE_MAX_CHANNELS
from spooky.models import AutoChannelNuke

from .entitlements import guild_has_spooky_premium

__all__ = ["reconcile_auto_perks", "reconcile_auto_perks_for_guild"]


async def reconcile_auto_perks_for_guild(bot: Spooky, guild_id: int) -> int:
    """Ensure auto nukes respect free limits when premium is absent.

    Keeps only the earliest configured channel when the guild does not have
    Spooky Premium, deleting any additional ``AutoChannelNuke`` rows.

    Returns
    -------
    int
        Number of configs deleted.
    """
    has_premium = await guild_has_spooky_premium(bot, guild_id)
    if has_premium:
        return 0

    configs = (
        await AutoChannelNuke.filter(guild_id=int(guild_id)).order_by("configured_at", "id").all()
    )
    if len(configs) <= FREE_MAX_CHANNELS:
        return 0

    drop_ids = [cfg.id for cfg in configs[FREE_MAX_CHANNELS:]]
    await AutoChannelNuke.filter(id__in=drop_ids).delete()
    return len(drop_ids)


async def reconcile_auto_perks(bot: Spooky) -> int:
    """Apply free-tier auto limits across all connected guilds."""
    removed = 0
    for guild in bot.guilds:
        removed += await reconcile_auto_perks_for_guild(bot, int(guild.id))
    return removed
