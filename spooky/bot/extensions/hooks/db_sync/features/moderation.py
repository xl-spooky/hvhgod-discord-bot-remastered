"""Cleanup and maintenance helpers for moderation data."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.bot.extensions.moderation.manager import (
    mark_ban_released,
    release_expired_bans as fetch_expired_bans,
)
from spooky.db import get_session
from spooky.models import (
    ModerationAction,
    ModerationActionType,
    ModerationCommandThreshold,
    ModerationCommandUsage,
)
from sqlalchemy import select

from ..utils import safe_delete

__all__ = [
    "ExpiredBanSummary",
    "ModerationMissingGuildPruneSummary",
    "ThresholdTargetPruneSummary",
    "UnbanReconciliationSummary",
    "delete_expired_command_usage",
    "delete_role_thresholds",
    "delete_user_thresholds",
    "prune_missing_guilds",
    "prune_threshold_targets",
    "reconcile_unbans",
    "release_expired_bans",
]


@dataclass(slots=True)
class ExpiredBanSummary:
    """Summaries produced after releasing expired bans."""

    processed: int
    succeeded: int
    failed: int
    skipped: int


@dataclass(slots=True)
class UnbanReconciliationSummary:
    """Summary statistics for unban reconciliation runs."""

    guilds_processed: int
    guilds_skipped: int
    active_bans_checked: int
    actions_removed: int


@dataclass(slots=True)
class ModerationMissingGuildPruneSummary:
    """Aggregated deletion counts when pruning moderation data for missing guilds."""

    kept_guilds: int
    actions_deleted: int
    thresholds_deleted: int
    usage_deleted: int


@dataclass(slots=True)
class ThresholdTargetPruneSummary:
    """Summaries produced after pruning threshold targets within a guild."""

    guild_id: int
    user_deleted: int
    role_deleted: int
    member_snapshot: int | None
    skipped_user_prune: bool


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> ModerationMissingGuildPruneSummary:
    """Remove moderation artifacts for guilds no longer tracked."""
    ids = {int(gid) for gid in kept_guild_ids}
    conditions: list[object] = []
    description = f"kept_guilds={len(ids)}"
    if ids:
        conditions.append(ModerationAction.guild_id.notin_(list(ids)))

    actions_deleted = await safe_delete(
        bot,
        ModerationAction,
        *conditions,
        title="DB Sync: prune moderation actions (missing guilds)",
        description=description,
    )
    threshold_conditions: list[object] = []
    usage_conditions: list[object] = []
    if ids:
        id_list = list(ids)
        threshold_conditions.append(ModerationCommandThreshold.guild_id.notin_(id_list))
        usage_conditions.append(ModerationCommandUsage.guild_id.notin_(id_list))

    thresholds_deleted = await safe_delete(
        bot,
        ModerationCommandThreshold,
        *threshold_conditions,
        title="DB Sync: prune moderation thresholds (missing guilds)",
        description=description,
    )

    usage_deleted = await safe_delete(
        bot,
        ModerationCommandUsage,
        *usage_conditions,
        title="DB Sync: prune moderation usage (missing guilds)",
        description=description,
    )

    return ModerationMissingGuildPruneSummary(
        kept_guilds=len(ids),
        actions_deleted=actions_deleted or 0,
        thresholds_deleted=thresholds_deleted or 0,
        usage_deleted=usage_deleted or 0,
    )


async def _guild_ban_targets(guild_id: int) -> set[int]:
    """Return IDs for active ban actions recorded in the database."""
    async with get_session() as session:
        result = await session.execute(
            select(ModerationAction.target_id).where(
                ModerationAction.guild_id == guild_id,
                ModerationAction.action == ModerationActionType.BAN.value,
                ModerationAction.released_at.is_(None),
            )
        )
        return {int(target_id) for target_id in result.scalars()}


async def reconcile_unbans(bot: Spooky) -> UnbanReconciliationSummary:
    """Drop stored bans that no longer exist in guild ban lists."""
    summary = UnbanReconciliationSummary(
        guilds_processed=0,
        guilds_skipped=0,
        active_bans_checked=0,
        actions_removed=0,
    )

    for guild in bot.guilds:
        summary.guilds_processed += 1
        banned_ids: set[int] | None = None

        with contextlib.suppress(Exception):
            bans = await guild.bans().flatten()
            banned_ids = {int(entry.user.id) for entry in bans}

        if banned_ids is None:
            summary.guilds_skipped += 1
            continue

        recorded_targets = await _guild_ban_targets(guild.id)
        summary.active_bans_checked += len(recorded_targets)

        reconciled = recorded_targets - banned_ids
        if not reconciled:
            continue

        removed = await safe_delete(
            bot,
            ModerationAction,
            ModerationAction.guild_id == guild.id,
            ModerationAction.action == ModerationActionType.BAN.value,
            ModerationAction.released_at.is_(None),
            ModerationAction.target_id.in_(list(reconciled)),
            title="DB Sync: prune reconciled unbans",
            description=f"guild={guild.id} removed={len(reconciled)}",
        )
        summary.actions_removed += removed or 0

    return summary


async def prune_threshold_targets(
    bot: Spooky,
    guild: disnake.Guild,
    *,
    member_ids: Iterable[int] | None = None,
) -> ThresholdTargetPruneSummary:
    """Prune moderation thresholds for missing role/user targets within ``guild``."""
    member_snapshot = None if member_ids is None else len({int(mid) for mid in member_ids})
    user_conditions: list[object] = [
        ModerationCommandThreshold.guild_id == guild.id,
        ModerationCommandThreshold.target_type == "user",
    ]

    if member_ids is None:
        skipped = True
        user_deleted = 0
    else:
        member_set = {int(member_id) for member_id in member_ids}
        skipped = False
        if member_set:
            user_conditions.append(ModerationCommandThreshold.target_id.notin_(list(member_set)))
        user_deleted = (
            await safe_delete(
                bot,
                ModerationCommandThreshold,
                *user_conditions,
                title="Moderation: prune threshold users (missing members)",
                description=f"guild={guild.id} snapshot={len(member_set)}",
            )
            or 0
        )

    role_ids = {int(role.id) for role in getattr(guild, "roles", [])}
    role_conditions: list[object] = [
        ModerationCommandThreshold.guild_id == guild.id,
        ModerationCommandThreshold.target_type == "role",
    ]
    if role_ids:
        role_conditions.append(ModerationCommandThreshold.target_id.notin_(list(role_ids)))

    role_deleted = (
        await safe_delete(
            bot,
            ModerationCommandThreshold,
            *role_conditions,
            title="Moderation: prune threshold roles (missing roles)",
            description=f"guild={guild.id} roles_snapshot={len(role_ids)}",
        )
        or 0
    )

    return ThresholdTargetPruneSummary(
        guild_id=guild.id,
        user_deleted=user_deleted,
        role_deleted=role_deleted,
        member_snapshot=member_snapshot,
        skipped_user_prune=skipped,
    )


async def delete_user_thresholds(bot: Spooky, guild_id: int, user_id: int) -> None:
    """Delete moderation thresholds for a departing member."""
    await safe_delete(
        bot,
        ModerationCommandThreshold,
        ModerationCommandThreshold.guild_id == guild_id,
        ModerationCommandThreshold.target_id == user_id,
        ModerationCommandThreshold.target_type == "user",
        title="Moderation: prune member thresholds on leave",
        description=f"guild={guild_id} user={user_id}",
    )


async def delete_role_thresholds(bot: Spooky, guild_id: int, role_id: int) -> None:
    """Delete moderation thresholds tied to a removed role."""
    await safe_delete(
        bot,
        ModerationCommandThreshold,
        ModerationCommandThreshold.guild_id == guild_id,
        ModerationCommandThreshold.target_id == role_id,
        ModerationCommandThreshold.target_type == "role",
        title="Moderation: prune role thresholds on delete",
        description=f"guild={guild_id} role={role_id}",
    )


async def release_expired_bans(bot: Spooky, *, reference_time: datetime) -> ExpiredBanSummary:
    """Automatically unban members whose timed bans have expired."""
    actions = await fetch_expired_bans(reference_time)
    if not actions:
        return ExpiredBanSummary(processed=0, succeeded=0, failed=0, skipped=0)

    summary = ExpiredBanSummary(
        processed=len(actions),
        succeeded=0,
        failed=0,
        skipped=0,
    )

    for action in actions:
        guild = bot.get_guild(action.guild_id)
        if guild is None:
            await mark_ban_released(action.id, released_at=reference_time)
            summary.skipped += 1
            continue

        target = disnake.Object(id=action.target_id)
        if not await _is_user_currently_banned(guild, target):
            await mark_ban_released(action.id, released_at=reference_time)
            summary.skipped += 1
            continue
        try:
            await guild.unban(target, reason="Timed ban expired")
        except disnake.Forbidden:
            logger.warning(
                "Missing permissions to unban user {} in guild {}",
                action.target_id,
                guild.id,
            )
            summary.failed += 1
            continue
        except disnake.NotFound:
            await mark_ban_released(action.id, released_at=reference_time)
            summary.skipped += 1
            continue
        except disnake.HTTPException as exc:  # pragma: no cover - network dependent
            logger.warning(
                "Failed to unban user {} in guild {}: {}",
                action.target_id,
                guild.id,
                exc,
            )
            summary.failed += 1
            continue

        await mark_ban_released(action.id, released_at=reference_time)
        summary.succeeded += 1

    return summary


async def _is_user_currently_banned(guild: disnake.Guild, user: disnake.abc.Snowflake) -> bool:
    """Return ``True`` when ``user`` is still banned in ``guild``."""
    with contextlib.suppress(disnake.NotFound):
        await guild.fetch_ban(user)
        return True

    return False


async def delete_expired_command_usage(bot: Spooky, *, reference_time: datetime) -> int:
    """Delete expired moderation command usage rows."""
    removed = await safe_delete(
        bot,
        ModerationCommandUsage,
        ModerationCommandUsage.expires_at <= reference_time,
        title="Moderation: prune expired command usage",
        description=f"reference={reference_time.isoformat()}",
    )
    return removed or 0
