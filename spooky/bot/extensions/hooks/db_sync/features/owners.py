"""DB sync helpers for owner authorization rows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import disnake
from spooky.bot import Spooky
from spooky.db import get_session
from spooky.models import GuildBotAuthorizationAccess, GuildBotConfigureAuthorization
from sqlalchemy import Select, select

from ..utils import safe_delete

__all__ = [
    "GuildMemberPruneSummary",
    "GuildMissingPruneSummary",
    "delete_guild_access",
    "delete_guild_artifacts",
    "delete_user_authorization",
    "prune_guild_members",
    "prune_missing_guilds",
]


@dataclass(slots=True)
class GuildMissingPruneSummary:
    kept_guilds: int
    authorizations_deleted: int
    access_deleted: int


@dataclass(slots=True)
class GuildMemberPruneSummary:
    guild_id: int
    stale_candidates: int
    deleted: int
    member_snapshot: int | None
    skipped_user_prune: bool


async def delete_guild_artifacts(bot: Spooky, guild_id: int) -> int:
    deleted_auth = await safe_delete(
        bot,
        GuildBotConfigureAuthorization,
        GuildBotConfigureAuthorization.guild_id == guild_id,
        title="DB Sync: delete owner authorizations (guild removed)",
        description=f"guild_id={guild_id}",
    )
    deleted_access = await safe_delete(
        bot,
        GuildBotAuthorizationAccess,
        GuildBotAuthorizationAccess.guild_id == guild_id,
        title="DB Sync: delete owner access scopes (guild removed)",
        description=f"guild_id={guild_id}",
    )

    return int(deleted_auth or 0) + int(deleted_access or 0)


async def delete_user_authorization(bot: Spooky, guild_id: int, user_id: int) -> int:
    return int(
        await safe_delete(
            bot,
            GuildBotConfigureAuthorization,
            GuildBotConfigureAuthorization.guild_id == guild_id,
            GuildBotConfigureAuthorization.user_id == user_id,
            title="DB Sync: delete owner authorization (member left)",
            description=f"guild_id={guild_id} user_id={user_id}",
        )
        or 0
    )


async def delete_guild_access(bot: Spooky, guild_id: int) -> int:
    return int(
        await safe_delete(
            bot,
            GuildBotAuthorizationAccess,
            GuildBotAuthorizationAccess.guild_id == guild_id,
            title="DB Sync: delete owner access scopes (guild removed)",
            description=f"guild_id={guild_id}",
        )
        or 0
    )


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> GuildMissingPruneSummary:
    ids = {int(gid) for gid in kept_guild_ids}
    conditions: list[object] = []
    access_conditions: list[object] = []
    if ids:
        conditions.append(GuildBotConfigureAuthorization.guild_id.notin_(list(ids)))
        access_conditions.append(GuildBotAuthorizationAccess.guild_id.notin_(list(ids)))

    deleted_authorizations = await safe_delete(
        bot,
        GuildBotConfigureAuthorization,
        *conditions,
        title="DB Sync: prune owner authorizations (missing guilds)",
        description=f"kept_guilds={len(ids)}",
    )

    deleted_access = await safe_delete(
        bot,
        GuildBotAuthorizationAccess,
        *access_conditions,
        title="DB Sync: prune owner access scopes (missing guilds)",
        description=f"kept_guilds={len(ids)}",
    )

    return GuildMissingPruneSummary(
        kept_guilds=len(ids),
        authorizations_deleted=int(deleted_authorizations or 0),
        access_deleted=int(deleted_access or 0),
    )


async def prune_guild_members(
    bot: Spooky, guild: disnake.Guild, *, member_ids: Iterable[int] | None = None
) -> GuildMemberPruneSummary:
    members = {int(mid) for mid in member_ids} if member_ids is not None else None
    skipped = members is None
    stale_users: set[int] = set()

    stmt: Select[tuple[int]] = select(GuildBotConfigureAuthorization.user_id).where(
        GuildBotConfigureAuthorization.guild_id == int(guild.id)
    )
    async with get_session() as session:
        result = await session.execute(stmt)
        rows = {int(row[0]) for row in result.all()}

    if members is not None:
        stale_users = {uid for uid in rows if uid not in members}

    deleted = 0
    if stale_users:
        deleted = await safe_delete(
            bot,
            GuildBotConfigureAuthorization,
            GuildBotConfigureAuthorization.guild_id == int(guild.id),
            GuildBotConfigureAuthorization.user_id.in_(list(stale_users)),
            title="DB Sync: prune owner authorizations (missing members)",
            description=f"guild_id={guild.id} stale={len(stale_users)}",
        )

    return GuildMemberPruneSummary(
        guild_id=int(guild.id),
        stale_candidates=len(stale_users),
        deleted=int(deleted or 0),
        member_snapshot=None if members is None else len(members),
        skipped_user_prune=skipped,
    )
