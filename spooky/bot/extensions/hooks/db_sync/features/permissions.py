"""Cleanup helpers for command management permission overrides."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import disnake
from spooky.bot import Spooky
from spooky.models import UserPermissionOverride

from ..utils import safe_delete

__all__ = [
    "PermissionMissingGuildSummary",
    "PermissionTargetPruneSummary",
    "delete_user_overrides",
    "prune_guild_targets",
    "prune_missing_guilds",
]


@dataclass(slots=True)
class PermissionMissingGuildSummary:
    """Aggregated deletion counts when pruning overrides for missing guilds."""

    kept_guilds: int
    overrides_deleted: int


@dataclass(slots=True)
class PermissionTargetPruneSummary:
    """Summaries produced when pruning permission overrides within a guild."""

    guild_id: int
    overrides_deleted: int
    member_snapshot: int | None
    skipped_user_prune: bool


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> PermissionMissingGuildSummary:
    """Remove permission overrides tied to guilds no longer tracked."""
    ids = {int(gid) for gid in kept_guild_ids}
    conditions: list[object] = []
    description = f"kept_guilds={len(ids)}"
    if ids:
        conditions.append(UserPermissionOverride.guild_id.notin_(list(ids)))

    overrides_deleted = await safe_delete(
        bot,
        UserPermissionOverride,
        *conditions,
        title="DB Sync: prune permission overrides (missing guilds)",
        description=description,
    )

    return PermissionMissingGuildSummary(
        kept_guilds=len(ids), overrides_deleted=overrides_deleted or 0
    )


async def prune_guild_targets(
    bot: Spooky, guild: disnake.Guild, *, member_ids: Iterable[int] | None = None
) -> PermissionTargetPruneSummary:
    """Prune permission overrides that point to departed members within ``guild``."""
    member_snapshot = None if member_ids is None else len({int(mid) for mid in member_ids})
    conditions: list[object] = [UserPermissionOverride.guild_id == guild.id]

    if member_ids is None:
        skipped = True
        overrides_deleted = 0
    else:
        skipped = False
        member_set = {int(member_id) for member_id in member_ids}
        if member_set:
            conditions.append(UserPermissionOverride.user_id.notin_(list(member_set)))
        overrides_deleted = (
            await safe_delete(
                bot,
                UserPermissionOverride,
                *conditions,
                title="Permissions: prune user overrides (missing members)",
                description=f"guild={guild.id} snapshot={len(member_set)}",
            )
            or 0
        )

    return PermissionTargetPruneSummary(
        guild_id=guild.id,
        overrides_deleted=overrides_deleted,
        member_snapshot=member_snapshot,
        skipped_user_prune=skipped,
    )


async def delete_user_overrides(bot: Spooky, guild_id: int, user_id: int) -> None:
    """Delete permission overrides for a member that left a guild."""
    await safe_delete(
        bot,
        UserPermissionOverride,
        UserPermissionOverride.guild_id == guild_id,
        UserPermissionOverride.user_id == user_id,
        title="Permissions: prune user overrides on leave",
        description=f"guild={guild_id} user={user_id}",
    )
