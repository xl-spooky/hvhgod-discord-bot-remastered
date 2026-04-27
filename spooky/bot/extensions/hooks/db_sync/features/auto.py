"""Helpers for auto actions such as scheduled channel nukes."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.core import emojis
from spooky.db import get_session
from spooky.ext.time import utcnow
from spooky.models import AutoChannelNuke
from spooky.models.cache import invalidate_channel
from sqlalchemy import delete, update

from ..utils import safe_delete

__all__ = [
    "AutoMissingChannelSummary",
    "AutoMissingGuildSummary",
    "AutoNukeRunSummary",
    "delete_guild_artifacts",
    "process_due_nukes",
    "prune_channel_configs",
    "prune_missing_channels",
    "prune_missing_guilds",
]


@dataclass(slots=True)
class AutoMissingGuildSummary:
    """Counts produced when pruning auto entries for stale guilds."""

    kept_guilds: int
    configs_deleted: int


@dataclass(slots=True)
class AutoNukeRunSummary:
    """Track outcomes from a single auto-nuke sweep."""

    processed: int
    succeeded: int
    failed: int
    dropped: int


@dataclass(slots=True)
class AutoMissingChannelSummary:
    """Counts produced when pruning auto entries for missing channels."""

    checked_guilds: int
    configs_deleted: int


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> AutoMissingGuildSummary:
    """Remove auto configs for guilds no longer tracked."""
    ids = {int(gid) for gid in kept_guild_ids}
    conditions: list[object] = []
    description = f"kept_guilds={len(ids)}"
    if ids:
        conditions.append(AutoChannelNuke.guild_id.notin_(list(ids)))

    configs_deleted = await safe_delete(
        bot,
        AutoChannelNuke,
        *conditions,
        title="Auto: prune missing guilds",
        description=description,
    )

    return AutoMissingGuildSummary(kept_guilds=len(ids), configs_deleted=configs_deleted or 0)


async def prune_missing_channels(bot: Spooky) -> AutoMissingChannelSummary:
    """Remove auto configs that target channels no longer in cache."""
    checked_guilds = 0
    configs_deleted = 0
    for guild in bot.guilds:
        checked_guilds += 1
        channel_ids = {int(channel.id) for channel in getattr(guild, "channels", [])}
        configs = await AutoChannelNuke.filter(guild_id=int(guild.id)).all()
        missing_config_ids = [cfg.id for cfg in configs if int(cfg.channel_id) not in channel_ids]
        if not missing_config_ids:
            continue

        deleted = await safe_delete(
            bot,
            AutoChannelNuke,
            AutoChannelNuke.id.in_(missing_config_ids),
            title="Auto: prune missing channels",
            description=f"guild={guild.id} missing={len(missing_config_ids)}",
        )
        configs_deleted += deleted or 0

        for cfg in configs:
            if cfg.id in missing_config_ids:
                invalidate_channel(int(cfg.channel_id))

    return AutoMissingChannelSummary(checked_guilds=checked_guilds, configs_deleted=configs_deleted)


async def delete_guild_artifacts(bot: Spooky, guild_id: int) -> None:
    """Delete all auto configs for ``guild_id``."""
    await safe_delete(
        bot,
        AutoChannelNuke,
        AutoChannelNuke.guild_id == guild_id,
        title="Auto: delete guild artifacts",
        description=f"guild={guild_id}",
    )


async def prune_channel_configs(bot: Spooky, channel: disnake.abc.GuildChannel) -> None:
    """Drop auto configs that reference ``channel``."""
    await safe_delete(
        bot,
        AutoChannelNuke,
        AutoChannelNuke.guild_id == channel.guild.id,
        AutoChannelNuke.channel_id == channel.id,
        title="Auto: prune channel config",
        description=f"guild={channel.guild.id} channel={channel.id}",
    )
    invalidate_channel(channel.id)


async def _reschedule_entry(config_id: int, *, channel_id: int, duration: timedelta) -> None:
    now = utcnow()
    nuke_at = now + duration

    async with get_session() as session:
        stmt = (
            update(AutoChannelNuke)
            .where(AutoChannelNuke.id == config_id)
            .values(
                channel_id=channel_id,
                configured_at=now,
                duration_seconds=int(duration.total_seconds()),
                nuke_at=nuke_at,
            )
        )
        await session.execute(stmt)


async def _drop_entry(config: AutoChannelNuke) -> None:
    async with get_session() as session:
        stmt = delete(AutoChannelNuke).where(AutoChannelNuke.id == config.id)
        await session.execute(stmt)
    invalidate_channel(config.channel_id)


async def _nuke_channel(bot: Spooky, config: AutoChannelNuke, *, reference_time: datetime) -> bool:
    guild = bot.get_guild(int(config.guild_id))
    if guild is None:
        await _drop_entry(config)
        return False

    channel = guild.get_channel(int(config.channel_id))
    if channel is None:
        await _drop_entry(config)
        return False

    if not isinstance(
        channel,
        (
            disnake.TextChannel,
            disnake.VoiceChannel,
            disnake.StageChannel,
            disnake.ForumChannel,
            disnake.CategoryChannel,
        ),
    ):
        await _drop_entry(config)
        return False

    try:
        position = getattr(channel, "position", None)
        category = getattr(channel, "category", None)
        reason = "Nuked by auto process"
        new_channel = await channel.clone(reason=reason)
        if category is not None and isinstance(
            new_channel,
            (
                disnake.TextChannel,
                disnake.VoiceChannel,
                disnake.StageChannel,
                disnake.ForumChannel,
            ),
        ):
            with contextlib.suppress(Exception):
                await new_channel.edit(category=category)
        if isinstance(position, int):
            with contextlib.suppress(Exception):
                await new_channel.edit(position=position)
        await _reschedule_entry(
            config.id,
            channel_id=new_channel.id,
            duration=timedelta(seconds=int(config.duration_seconds)),
        )
        with contextlib.suppress(Exception):
            await channel.delete(reason=reason)
        if isinstance(new_channel, disnake.TextChannel):
            with contextlib.suppress(Exception):
                timestamp = int(reference_time.timestamp())
                await new_channel.send(
                    f"{emojis.bolt} Channel nuked by the auto process at <t:{timestamp}:R>."
                )
    except Exception:
        logger.exception("Failed to auto-nuke channel", channel=config.channel_id)
        delay = reference_time + timedelta(minutes=30)
        async with get_session() as session:
            stmt = (
                update(AutoChannelNuke).where(AutoChannelNuke.id == config.id).values(nuke_at=delay)
            )
            await session.execute(stmt)
        return False
    else:
        return True


async def process_due_nukes(
    bot: Spooky, *, reference_time: datetime | None = None
) -> AutoNukeRunSummary:
    """Execute auto channel nukes whose deadline has passed."""
    now = reference_time or utcnow()
    due = await AutoChannelNuke.filter(nuke_at__lte=now).all()
    if not due:
        return AutoNukeRunSummary(processed=0, succeeded=0, failed=0, dropped=0)

    succeeded = 0
    failed = 0
    dropped = 0

    for config in due:
        before = await AutoChannelNuke.filter(id=config.id).first()
        if before is None:
            dropped += 1
            continue

        ok = await _nuke_channel(bot, before, reference_time=now)
        if ok:
            succeeded += 1
        else:
            failed += 1

    return AutoNukeRunSummary(
        processed=len(due), succeeded=succeeded, failed=failed, dropped=dropped
    )
