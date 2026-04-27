"""Command gating maintenance helpers for the DB sync pipeline.

This module houses cleanup utilities for the command gating tables:

- :class:`~spooky.models.GuildCommandDisabled`
- :class:`~spooky.models.GuildCommandRoleOverride`
- :class:`~spooky.models.GuildCommandUserOverride`

They are used by the database synchronization cog to prune rows that refer to
guilds, roles, or users that no longer exist, and to react to runtime events
such as member or role deletions.

Design notes
------------
- Functions are **idempotent** and safe to run repeatedly.
- All write operations go through :func:`..utils.safe_delete` for telemetry and
  best-effort error handling.
- Network/API calls to Discord (e.g., :meth:`disnake.Guild.fetch_member`) are
  minimized and only performed when necessary to confirm that a user is truly
  gone from a guild.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import disnake
from spooky.bot import Spooky
from spooky.db import get_session
from spooky.models import GuildCommandDisabled, GuildCommandRoleOverride, GuildCommandUserOverride
from spooky.models.cache import ensure_member
from sqlalchemy import Select, select

from ..utils import safe_delete

__all__ = [
    "GuildMissingPruneSummary",
    "GuildTargetPruneSummary",
    "delete_guild_artifacts",
    "delete_role_overrides",
    "delete_user_overrides",
    "prune_guild_targets",
    "prune_missing_guilds",
]


@dataclass(slots=True)
class GuildMissingPruneSummary:
    """Aggregated deletion counts when pruning rows for departed guilds.

    Attributes
    ----------
    kept_guilds : int
        Number of guild IDs preserved (not pruned) during the operation.
    disables_deleted : int
        Count of rows removed from :class:`GuildCommandDisabled`.
    role_deleted : int
        Count of rows removed from :class:`GuildCommandRoleOverride`.
    user_deleted : int
        Count of rows removed from :class:`GuildCommandUserOverride`.
    """

    kept_guilds: int
    disables_deleted: int
    role_deleted: int
    user_deleted: int


@dataclass(slots=True)
class GuildTargetPruneSummary:
    """Summary information produced after pruning a guild's overrides.

    Attributes
    ----------
    guild_id : int
        Target guild whose overrides were pruned.
    role_deleted : int
        Number of role-override rows deleted.
    user_deleted : int
        Number of user-override rows deleted.
    member_snapshot : int | None
        Size of the member ID snapshot used to validate user presence. ``None``
        indicates we could not obtain a member list (e.g., member cache disabled
        and no explicit ``member_ids`` provided).
    stale_user_candidates : int
        Number of user IDs identified as stale (no longer members) before delete.
    skipped_user_prune : bool
        ``True`` when user pruning was skipped due to missing member information.
    """

    guild_id: int
    role_deleted: int
    user_deleted: int
    member_snapshot: int | None
    stale_user_candidates: int
    skipped_user_prune: bool


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> GuildMissingPruneSummary:
    """Remove command-gating rows for guilds **not** present in ``kept_guild_ids``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry and context in :func:`safe_delete`.
    kept_guild_ids : Iterable[int]
        Exact set of guild IDs that should be preserved. All rows referencing
        guilds outside this set are removed.

    Returns
    -------
    GuildMissingPruneSummary
        Aggregated deletion counts across the three gating tables.

    Notes
    -----
    - Passing an empty iterable will prune **all** rows in the gating tables.
    """
    ids = {int(gid) for gid in kept_guild_ids}
    description = f"kept_guilds={len(ids)}"

    disabled_conditions: list[object] = []
    role_conditions: list[object] = []
    user_conditions: list[object] = []
    if ids:
        id_list = list(ids)
        disabled_conditions.append(GuildCommandDisabled.guild_id.notin_(id_list))
        role_conditions.append(GuildCommandRoleOverride.guild_id.notin_(id_list))
        user_conditions.append(GuildCommandUserOverride.guild_id.notin_(id_list))

    disables_deleted = await safe_delete(
        bot,
        GuildCommandDisabled,
        *disabled_conditions,
        title="DB Sync: prune command disables (missing guilds)",
        description=description,
    )

    role_deleted = await safe_delete(
        bot,
        GuildCommandRoleOverride,
        *role_conditions,
        title="DB Sync: prune command role overrides (missing guilds)",
        description=description,
    )

    user_deleted = await safe_delete(
        bot,
        GuildCommandUserOverride,
        *user_conditions,
        title="DB Sync: prune command user overrides (missing guilds)",
        description=description,
    )

    return GuildMissingPruneSummary(
        kept_guilds=len(ids),
        disables_deleted=disables_deleted or 0,
        role_deleted=role_deleted or 0,
        user_deleted=user_deleted or 0,
    )


async def prune_guild_targets(
    bot: Spooky,
    guild: disnake.Guild,
    *,
    member_ids: Iterable[int] | None = None,
) -> GuildTargetPruneSummary:
    """Prune role/user overrides for a guild when the targets no longer exist.

    This performs two phases:
    1) **Role overrides:** delete entries whose ``role_id`` no longer exists in
       ``guild.roles``.
    2) **User overrides:** delete entries whose ``user_id`` is not a current
       guild member. If a member list cannot be obtained, user pruning is
       **skipped** and reported in the summary.

    Parameters
    ----------
    bot : Spooky
        Running bot instance for telemetry and context.
    guild : disnake.Guild
        Guild to evaluate for stale role and user overrides.
    member_ids : Iterable[int] | None, optional
        Optional authoritative snapshot of current member IDs. When omitted, the
        function uses ``guild.members`` if available; otherwise user pruning is
        skipped to avoid excessive API calls.

    Returns
    -------
    GuildTargetPruneSummary
        Counts and metadata describing what was pruned and what was skipped.

    Notes
    -----
    - To avoid heavy API usage, this function only calls
      :meth:`disnake.Guild.fetch_member` for user IDs that are not found in the
      provided (or derived) member snapshot **and** not present in the local
      cache (``guild.get_member``).
    """
    guild_id = int(guild.id)
    role_ids = [int(role.id) for role in getattr(guild, "roles", [])]
    if member_ids is not None:
        member_ids = list(member_ids)

    conditions: list[object] = [GuildCommandRoleOverride.guild_id == guild_id]
    if role_ids:
        conditions.append(GuildCommandRoleOverride.role_id.notin_(role_ids))
    role_deleted = await safe_delete(
        bot,
        GuildCommandRoleOverride,
        *conditions,
        title="DB Sync: prune command role overrides (missing roles)",
        description=f"guild={guild_id} roles={len(role_ids)}",
    )
    role_deleted = role_deleted or 0

    member_ids = _ensure_member_ids(guild, member_ids)
    if member_ids is None:
        return GuildTargetPruneSummary(
            guild_id=guild_id,
            role_deleted=role_deleted,
            user_deleted=0,
            member_snapshot=None,
            stale_user_candidates=0,
            skipped_user_prune=True,
        )

    stale_user_ids = await _identify_stale_user_overrides(bot, guild, member_ids)
    if not stale_user_ids:
        return GuildTargetPruneSummary(
            guild_id=guild_id,
            role_deleted=role_deleted,
            user_deleted=0,
            member_snapshot=len(member_ids),
            stale_user_candidates=0,
            skipped_user_prune=False,
        )

    user_deleted = await safe_delete(
        bot,
        GuildCommandUserOverride,
        GuildCommandUserOverride.guild_id == guild_id,
        GuildCommandUserOverride.user_id.in_(list(stale_user_ids)),
        title="DB Sync: prune command user overrides (missing members)",
        description=f"guild={guild_id} removed={len(stale_user_ids)}",
    )
    return GuildTargetPruneSummary(
        guild_id=guild_id,
        role_deleted=role_deleted,
        user_deleted=user_deleted or 0,
        member_snapshot=len(member_ids),
        stale_user_candidates=len(stale_user_ids),
        skipped_user_prune=False,
    )


async def delete_guild_artifacts(bot: Spooky, guild_id: int) -> None:
    """Delete all command-gating rows for ``guild_id``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry in :func:`safe_delete`.
    guild_id : int
        The guild whose gating data should be removed.

    Notes
    -----
    - Intended to be called on **guild remove** events or irreversible cleanup.
    """
    await safe_delete(
        bot,
        GuildCommandDisabled,
        GuildCommandDisabled.guild_id == int(guild_id),
        title="DB Sync: delete command disables (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        GuildCommandRoleOverride,
        GuildCommandRoleOverride.guild_id == int(guild_id),
        title="DB Sync: delete command role overrides (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        GuildCommandUserOverride,
        GuildCommandUserOverride.guild_id == int(guild_id),
        title="DB Sync: delete command user overrides (guild remove)",
        description=f"guild={guild_id}",
    )


async def delete_role_overrides(bot: Spooky, guild_id: int, role_id: int) -> None:
    """Delete role overrides tied to ``role_id`` within ``guild_id``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry in :func:`safe_delete`.
    guild_id : int
        Guild containing the role override rows.
    role_id : int
        The role whose overrides should be removed.

    Use Cases
    ---------
    - Triggered on **role delete** events to keep the table clean.
    """
    await safe_delete(
        bot,
        GuildCommandRoleOverride,
        GuildCommandRoleOverride.guild_id == int(guild_id),
        GuildCommandRoleOverride.role_id == int(role_id),
        title="DB Sync: delete command role overrides (role remove)",
        description=f"guild={guild_id} role={role_id}",
    )


async def delete_user_overrides(bot: Spooky, guild_id: int, user_id: int) -> None:
    """Delete user overrides tied to ``user_id`` within ``guild_id``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry in :func:`safe_delete`.
    guild_id : int
        Guild containing the user override rows.
    user_id : int
        The user whose overrides should be removed.

    Use Cases
    ---------
    - Triggered on **member remove** to discard personalized overrides.
    """
    await safe_delete(
        bot,
        GuildCommandUserOverride,
        GuildCommandUserOverride.guild_id == int(guild_id),
        GuildCommandUserOverride.user_id == int(user_id),
        title="DB Sync: delete command user overrides (member remove)",
        description=f"guild={guild_id} user={user_id}",
    )


def _ensure_member_ids(guild: disnake.Guild, member_ids: Iterable[int] | None) -> set[int] | None:
    """Return a set of member IDs for ``guild`` or ``None`` if unavailable.

    Parameters
    ----------
    guild : disnake.Guild
        Guild from which to derive member IDs.
    member_ids : Iterable[int] | None
        Optional explicit snapshot to use verbatim.

    Returns
    -------
    set[int] | None
        A set of member IDs, or ``None`` when no snapshot could be derived.

    Notes
    -----
    - When ``member_ids`` is provided, it is normalized into a ``set[int]`` and
      returned immediately.
    - Otherwise this attempts to use ``guild.members``; if empty/unavailable,
      ``None`` is returned so the caller can decide whether to skip user pruning.
    """
    if member_ids is not None:
        return {int(mid) for mid in member_ids}

    members = getattr(guild, "members", None)
    if not members:
        return None
    return {int(member.id) for member in members}


async def _identify_stale_user_overrides(
    bot: Spooky, guild: disnake.Guild, member_ids: set[int]
) -> set[int]:
    """Compute user IDs whose overrides should be pruned for ``guild``.

    A user is considered **stale** when:
    - Their ID appears in :class:`GuildCommandUserOverride` for the guild,
    - The ID is **not** in the provided ``member_ids`` snapshot,
    - ``guild.get_member`` returns ``None``, and
    - ``guild.fetch_member`` raises :class:`disnake.NotFound` or
      :class:`disnake.Forbidden`.

    Parameters
    ----------
    bot : Spooky
        Running bot instance for resolving members.
    guild : disnake.Guild
        Guild context for resolving member presence.
    member_ids : set[int]
        Authoritative in-memory snapshot of current members.

    Returns
    -------
    set[int]
        User IDs that are safe to delete from :class:`GuildCommandUserOverride`.

    Notes
    -----
    - HTTP errors (:class:`disnake.HTTPException`) are treated as inconclusive
      and that user ID is **not** considered stale in this pass.
    """
    stmt: Select[tuple[int]] = select(GuildCommandUserOverride.user_id).where(
        GuildCommandUserOverride.guild_id == int(guild.id)
    )

    async with get_session() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    candidate_ids = {int(user_id) for user_id in rows}
    stale: set[int] = set()
    for user_id in candidate_ids:
        if user_id in member_ids:
            continue

        try:
            member = await ensure_member(bot, int(guild.id), user_id)
        except disnake.HTTPException:
            continue

        if member is None:
            stale.add(user_id)

    return stale
