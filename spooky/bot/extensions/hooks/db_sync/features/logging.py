"""Logging cleanup helpers for DB synchronization.

These helpers keep the logging settings table in sync with Discord state by
removing rows tied to missing guilds, deleted channels, or removed webhooks.
They mirror the defensive patterns used by other DB sync features (e.g.,
``snipe``) by leaning on :func:`guard_db_ready` and :func:`safe_delete`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.core import checks
from spooky.db import get_session
from spooky.models import GuildLoggingSettings, ensure_channel
from sqlalchemy import select

from ..utils import guard_db_ready, safe_delete

__all__ = [
    "LoggingCleanupSummary",
    "LoggingGuildPruneSummary",
    "prune_channel_targets",
    "prune_missing_guilds",
    "prune_missing_webhooks",
    "reconcile_logging_targets",
]


@dataclass(slots=True)
class LoggingCleanupSummary:
    """Aggregated cleanup counts for logging topics."""

    evaluated: int = 0
    cleared_topics: int = 0
    webhooks_deleted: int = 0

    def add(self, other: LoggingCleanupSummary) -> LoggingCleanupSummary:
        self.evaluated += other.evaluated
        self.cleared_topics += other.cleared_topics
        self.webhooks_deleted += other.webhooks_deleted
        return self


@dataclass(slots=True)
class LoggingGuildPruneSummary:
    """Cleanup counts when pruning logging rows for missing guilds."""

    kept_guilds: int
    settings_deleted: int


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> LoggingGuildPruneSummary:
    """Remove logging settings rows for guilds the bot is no longer in."""
    ids = {int(gid) for gid in kept_guild_ids}
    description = f"kept_guilds={len(ids)}"

    conditions: list[object] = []
    if ids:
        conditions.append(GuildLoggingSettings.guild_id.notin_(list(ids)))

    deleted = await safe_delete(
        bot,
        GuildLoggingSettings,
        *conditions,
        title="DB Sync: prune logging settings (missing guilds)",
        description=description,
    )

    return LoggingGuildPruneSummary(kept_guilds=len(ids), settings_deleted=int(deleted or 0))


async def reconcile_logging_targets(bot: Spooky) -> LoggingCleanupSummary:
    """Sweep all guild logging rows for missing channels or webhooks."""
    if not await guard_db_ready(bot):
        return LoggingCleanupSummary()

    summary = LoggingCleanupSummary()
    for guild in bot.guilds:
        guild_summary = await _sweep_guild_targets(bot, guild)
        summary.add(guild_summary)

    logger.info(
        "Logging sweep summary: evaluated={} cleared_topics={} webhooks_deleted={}",
        summary.evaluated,
        summary.cleared_topics,
        summary.webhooks_deleted,
    )
    return summary


async def prune_channel_targets(
    bot: Spooky, channel: disnake.abc.GuildChannel
) -> LoggingCleanupSummary:
    """Remove logging settings bound to a channel that was deleted."""
    if not checks.db_enabled():
        return LoggingCleanupSummary()

    rows = await _fetch_rows(channel.guild.id, channel_id=int(channel.id))
    reason = f"Logging cleanup: channel deleted ({channel.id})"
    return await _clear_logging_rows(bot, rows, reason=reason)


async def prune_missing_webhooks(
    bot: Spooky, channel: disnake.TextChannel | disnake.NewsChannel
) -> LoggingCleanupSummary:
    """Remove logging settings whose webhook was deleted in ``channel``."""
    if not checks.db_enabled():
        return LoggingCleanupSummary()

    rows = await _fetch_rows(channel.guild.id, channel_id=int(channel.id))
    try:
        webhook_ids = {int(webhook.id) for webhook in await channel.webhooks()}
    except Exception:
        webhook_ids = set()

    stale_rows = [row for row in rows if row.webhook_id and int(row.webhook_id) not in webhook_ids]
    reason = f"Logging cleanup: webhook missing for channel {channel.id}"
    return await _clear_logging_rows(bot, stale_rows, reason=reason)


async def _sweep_guild_targets(bot: Spooky, guild: disnake.Guild) -> LoggingCleanupSummary:
    rows = await _fetch_rows(guild.id)
    summary = LoggingCleanupSummary()
    channel_webhooks: dict[int, set[int]] = {}

    stale_rows: list[GuildLoggingSettings] = []
    for row in rows:
        summary.evaluated += 1
        channel = await ensure_channel(bot, int(row.channel_id)) if row.channel_id else None
        if not isinstance(channel, (disnake.TextChannel, disnake.NewsChannel)):
            stale_rows.append(row)
            continue

        if row.webhook_id is None:
            continue

        webhook_ids = channel_webhooks.get(channel.id)
        if webhook_ids is None:
            try:
                webhook_ids = {int(webhook.id) for webhook in await channel.webhooks()}
            except Exception:
                webhook_ids = set()
            channel_webhooks[channel.id] = webhook_ids

        if int(row.webhook_id) not in webhook_ids:
            stale_rows.append(row)

    cleared_summary = await _clear_logging_rows(
        bot,
        stale_rows,
        reason="Logging cleanup: missing channel or webhook",
    )
    summary.add(cleared_summary)
    return summary


async def _fetch_rows(
    guild_id: int, *, channel_id: int | None = None
) -> Sequence[GuildLoggingSettings]:
    stmt = select(GuildLoggingSettings).where(GuildLoggingSettings.guild_id == guild_id)
    if channel_id is not None:
        stmt = stmt.where(GuildLoggingSettings.channel_id == channel_id)

    async with get_session() as session:
        result = await session.execute(stmt)
        return list(result.scalars())


async def _clear_logging_rows(
    bot: Spooky, rows: Sequence[GuildLoggingSettings], *, reason: str
) -> LoggingCleanupSummary:
    summary = LoggingCleanupSummary(evaluated=len(rows))
    if not rows:
        return summary

    for row in rows:
        if row.webhook_id is None:
            continue
        with contextlib.suppress(Exception):
            webhook = await bot.fetch_webhook(int(row.webhook_id))
            if getattr(webhook, "guild_id", None) == row.guild_id:
                await webhook.delete(reason=reason)
                summary.webhooks_deleted += 1

    ids = [int(row.id) for row in rows]
    if ids:
        deleted = await safe_delete(
            bot,
            GuildLoggingSettings,
            GuildLoggingSettings.id.in_(ids),
            title="DB Sync: prune logging settings (stale targets)",
            description=f"rows={len(ids)} reason={reason}",
        )
        summary.cleared_topics += int(deleted or 0)

    return summary
