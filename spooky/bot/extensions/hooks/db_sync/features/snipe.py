"""Snipe feature maintenance helpers.

This module contains high-level cleanup utilities used by the DB sync pipeline
to keep *snipe*-related tables consistent and compact:

- ``prune_missing_guilds``: remove rows that belong to guilds the bot no longer tracks.
- ``delete_guild_artifacts``: remove a guild row and all related snipe artifacts.
- ``delete_expired_entries``: purge time-expired snipe rows.
- ``prune_missing_opt_outs``: remove per-guild user opt-outs for users who left.

All destructive operations are funneled through :func:`safe_delete`, which is
responsible for executing the deletion, handling errors, and emitting telemetry.

Design notes
------------
- Functions are **idempotent** and safe to re-run.
- Database I/O is minimized; remote Discord API checks are performed only when
  cache/snapshots are insufficient to establish absence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.db import get_session
from spooky.models import (
    Guild as GuildModel,
    GuildSnipeSettings,
    SnipeEdit,
    SnipeMessage,
    SnipeSticker,
    UserSnipeOptOut,
)
from spooky.models.cache import ensure_member
from sqlalchemy import Select, select

from ..utils import safe_delete

__all__ = [
    "ExpiredSnipeSummary",
    "OptOutPruneSummary",
    "SnipeGuildPruneSummary",
    "delete_expired_entries",
    "delete_guild_artifacts",
    "delete_user_opt_out",
    "prune_missing_guilds",
    "prune_missing_opt_outs",
]


@dataclass(slots=True)
class SnipeGuildPruneSummary:
    """Aggregated counts when pruning snipe rows for departed guilds.

    Attributes
    ----------
    kept_guilds : int
        Number of guild IDs preserved (i.e., **not** pruned).
    messages_deleted : int
        Deleted rows in :class:`~spooky.models.SnipeMessage`.
    edits_deleted : int
        Deleted rows in :class:`~spooky.models.SnipeEdit`.
    stickers_deleted : int
        Deleted rows in :class:`~spooky.models.SnipeSticker`.
    opt_out_deleted : int
        Deleted rows in :class:`~spooky.models.UserSnipeOptOut`.
    settings_deleted : int
        Deleted rows in :class:`~spooky.models.GuildSnipeSettings`.
    """

    kept_guilds: int
    messages_deleted: int
    edits_deleted: int
    stickers_deleted: int
    opt_out_deleted: int
    settings_deleted: int


@dataclass(slots=True)
class ExpiredSnipeSummary:
    """Counts of expired snipe artifacts removed during cleanup.

    Attributes
    ----------
    messages_deleted : int
        Number of expired message rows removed.
    edits_deleted : int
        Number of expired edit rows removed.
    stickers_deleted : int
        Number of expired sticker rows removed.
    """

    messages_deleted: int
    edits_deleted: int
    stickers_deleted: int


@dataclass(slots=True)
class OptOutPruneSummary:
    """Summary produced after pruning guild-level snipe opt-outs.

    Attributes
    ----------
    guild_id : int
        The guild whose opt-outs were examined.
    evaluated : int
        Total opt-out rows evaluated.
    stale : int
        How many opt-outs were determined to belong to non-members.
    deleted : int
        How many rows were actually deleted.
    member_snapshot : int | None
        Size of the member snapshot used to validate presence. ``None`` means
        we couldn't obtain a snapshot, so user pruning was skipped.
    skipped_user_prune : bool
        ``True`` if user pruning was skipped due to lack of member data.
    """

    guild_id: int
    evaluated: int
    stale: int
    deleted: int
    member_snapshot: int | None
    skipped_user_prune: bool


async def prune_missing_guilds(
    bot: Spooky, kept_guild_ids: Iterable[int]
) -> SnipeGuildPruneSummary:
    """Prune all snipe/config rows for guilds **not** in ``kept_guild_ids``.

    For each snipe-related model, deletes rows whose ``guild_id`` is *not* among
    the provided IDs. Use this after a one-shot snapshot of the bot's currently
    connected guilds to remove data for departed guilds.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry/context in :func:`safe_delete`.
    kept_guild_ids : Iterable[int]
        Iterable of guild IDs to retain. Any rows with a ``guild_id`` not in this
        set will be deleted.

    Returns
    -------
    SnipeGuildPruneSummary
        Aggregated deletion counts for each snipe-related table.

    Notes
    -----
    - The iterable is normalized to a **deduplicated set of ints** before use.
    - When ``kept_guild_ids`` is empty, the helper removes **all** rows.
    """
    ids = {int(gid) for gid in kept_guild_ids}
    description = f"kept_guilds={len(ids)}"

    message_conditions: list[object] = []
    edit_conditions: list[object] = []
    sticker_conditions: list[object] = []
    opt_out_conditions: list[object] = []
    settings_conditions: list[object] = []
    if ids:
        id_list = list(ids)
        message_conditions.append(SnipeMessage.guild_id.notin_(id_list))
        edit_conditions.append(SnipeEdit.guild_id.notin_(id_list))
        sticker_conditions.append(SnipeSticker.guild_id.notin_(id_list))
        opt_out_conditions.append(UserSnipeOptOut.guild_id.notin_(id_list))
        settings_conditions.append(GuildSnipeSettings.guild_id.notin_(id_list))

    messages_deleted = await safe_delete(
        bot,
        SnipeMessage,
        *message_conditions,
        title="DB Sync: prune snipe messages (missing guilds)",
        description=description,
    )

    edits_deleted = await safe_delete(
        bot,
        SnipeEdit,
        *edit_conditions,
        title="DB Sync: prune snipe edits (missing guilds)",
        description=description,
    )

    stickers_deleted = await safe_delete(
        bot,
        SnipeSticker,
        *sticker_conditions,
        title="DB Sync: prune snipe stickers (missing guilds)",
        description=description,
    )

    opt_out_deleted = await safe_delete(
        bot,
        UserSnipeOptOut,
        *opt_out_conditions,
        title="DB Sync: prune user opt-outs (missing guilds)",
        description=description,
    )

    settings_deleted = await safe_delete(
        bot,
        GuildSnipeSettings,
        *settings_conditions,
        title="DB Sync: prune guild snipe settings (missing guilds)",
        description=description,
    )

    return SnipeGuildPruneSummary(
        kept_guilds=len(ids),
        messages_deleted=messages_deleted or 0,
        edits_deleted=edits_deleted or 0,
        stickers_deleted=stickers_deleted or 0,
        opt_out_deleted=opt_out_deleted or 0,
        settings_deleted=settings_deleted or 0,
    )


async def delete_guild_artifacts(bot: Spooky, guild_id: int) -> None:
    """Delete a guild row and **all** associated snipe artifacts.

    Removes the guild record itself plus any related snipe messages, edits,
    stickers, and per-user opt-out flags.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry/context in :func:`safe_delete`.
    guild_id : int
        The guild ID whose data should be removed.

    Notes
    -----
    - Each table is pruned via a separate :func:`safe_delete` call so partial
      failures can be telemetered and retried independently.
    """
    logger.info("Snipe: deleting guild artifacts for guild={}", guild_id)
    await safe_delete(
        bot,
        GuildModel,
        GuildModel.id == int(guild_id),
        title="DB Sync: delete guild row",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        SnipeMessage,
        SnipeMessage.guild_id == int(guild_id),
        title="DB Sync: delete snipe messages (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        SnipeEdit,
        SnipeEdit.guild_id == int(guild_id),
        title="DB Sync: delete snipe edits (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        SnipeSticker,
        SnipeSticker.guild_id == int(guild_id),
        title="DB Sync: delete snipe stickers (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        UserSnipeOptOut,
        UserSnipeOptOut.guild_id == int(guild_id),
        title="DB Sync: delete user opt-outs (guild remove)",
        description=f"guild={guild_id}",
    )
    await safe_delete(
        bot,
        GuildSnipeSettings,
        GuildSnipeSettings.guild_id == int(guild_id),
        title="DB Sync: delete guild snipe settings (guild remove)",
        description=f"guild={guild_id}",
    )


async def delete_user_opt_out(bot: Spooky, guild_id: int, user_id: int) -> None:
    """Delete snipe opt-out rows for a specific ``user_id`` in ``guild_id``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry/context in :func:`safe_delete`.
    guild_id : int
        Guild containing the opt-out rows.
    user_id : int
        Target user whose opt-out entries should be removed.

    Use Cases
    ---------
    - Triggered on **member remove** to discard per-user exclusions.
    """
    await safe_delete(
        bot,
        UserSnipeOptOut,
        UserSnipeOptOut.guild_id == int(guild_id),
        UserSnipeOptOut.user_id == int(user_id),
        title="DB Sync: delete snipe opt-out (member remove)",
        description=f"guild={guild_id} user={user_id}",
    )


async def delete_expired_entries(
    bot: Spooky,
    *,
    reference_time: datetime | None = None,
) -> ExpiredSnipeSummary:
    """Delete expired snipe rows across messages, edits, and stickers.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry/context in :func:`safe_delete`.
    reference_time : datetime | None, keyword-only
        Optional timestamp to evaluate expirations against. If omitted, the
        current UTC time is used. If supplied, it **should be timezone-aware**.

    Returns
    -------
    ExpiredSnipeSummary
        Aggregated deletion counts for expired messages, edits, and stickers.

    Notes
    -----
    - Actual deletion and error reporting are delegated to :func:`safe_delete`.
    """
    now = reference_time or datetime.now(UTC)
    messages_deleted = await safe_delete(
        bot,
        SnipeMessage,
        SnipeMessage.expires_at < now,
        title="DB Sync: cleanup expired snipe messages",
        description="Periodic cleanup",
    )
    edits_deleted = await safe_delete(
        bot,
        SnipeEdit,
        SnipeEdit.expires_at < now,
        title="DB Sync: cleanup expired snipe edits",
        description="Periodic cleanup",
    )
    stickers_deleted = await safe_delete(
        bot,
        SnipeSticker,
        SnipeSticker.expires_at < now,
        title="DB Sync: cleanup expired snipe stickers",
        description="Periodic cleanup",
    )

    return ExpiredSnipeSummary(
        messages_deleted=messages_deleted or 0,
        edits_deleted=edits_deleted or 0,
        stickers_deleted=stickers_deleted or 0,
    )


async def prune_missing_opt_outs(
    bot: Spooky,
    guild: disnake.Guild,
    *,
    member_ids: Iterable[int] | None = None,
) -> OptOutPruneSummary:
    """Prune snipe opt-outs for users who are no longer in ``guild``.

    Parameters
    ----------
    bot : Spooky
        Running bot instance used for telemetry/context in :func:`safe_delete`.
    guild : disnake.Guild
        Guild whose user opt-outs are being validated.
    member_ids : Iterable[int] | None, keyword-only
        Optional authoritative snapshot of current member IDs. When omitted, the
        function uses ``guild.members`` if available; otherwise user pruning is
        **skipped** and reported accordingly.

    Returns
    -------
    OptOutPruneSummary
        Summary including counts and whether user pruning was skipped.

    Notes
    -----
    - To limit API calls, a user is considered stale only if:
      (1) not in the provided snapshot, (2) not found in ``guild.get_member``,
      and (3) ``guild.fetch_member`` raises ``NotFound`` or ``Forbidden``.
    """
    known_members = _normalize_member_ids(guild, member_ids)
    if known_members is None:
        return OptOutPruneSummary(
            guild_id=int(guild.id),
            evaluated=0,
            stale=0,
            deleted=0,
            member_snapshot=None,
            skipped_user_prune=True,
        )

    stmt: Select[tuple[int]] = select(UserSnipeOptOut.user_id).where(
        UserSnipeOptOut.guild_id == int(guild.id)
    )

    async with get_session() as session:
        result = await session.execute(stmt)
        user_ids = {int(user_id) for user_id in result.scalars().all()}

    stale_ids: set[int] = set()
    for user_id in user_ids:
        if user_id in known_members:
            continue

        try:
            member = await ensure_member(bot, int(guild.id), user_id)
        except disnake.HTTPException:
            continue

        if member is None:
            stale_ids.add(user_id)

    if not stale_ids:
        return OptOutPruneSummary(
            guild_id=int(guild.id),
            evaluated=len(user_ids),
            stale=0,
            deleted=0,
            member_snapshot=len(known_members),
            skipped_user_prune=False,
        )

    deleted = await safe_delete(
        bot,
        UserSnipeOptOut,
        UserSnipeOptOut.guild_id == int(guild.id),
        UserSnipeOptOut.user_id.in_(list(stale_ids)),
        title="DB Sync: prune snipe opt-outs (missing members)",
        description=f"guild={guild.id} removed={len(stale_ids)}",
    )
    return OptOutPruneSummary(
        guild_id=int(guild.id),
        evaluated=len(user_ids),
        stale=len(stale_ids),
        deleted=deleted or 0,
        member_snapshot=len(known_members),
        skipped_user_prune=False,
    )


def _normalize_member_ids(
    guild: disnake.Guild, member_ids: Iterable[int] | None
) -> set[int] | None:
    """Return a normalized member ID snapshot for ``guild``.

    Parameters
    ----------
    guild : disnake.Guild
        Guild from which to derive members if a snapshot isn't provided.
    member_ids : Iterable[int] | None
        Optional explicit list/iterable of member IDs to use verbatim.

    Returns
    -------
    set[int] | None
        Set of member IDs, or ``None`` if no snapshot could be derived.

    Notes
    -----
    - When ``member_ids`` is provided, it is normalized into a ``set[int]``.
    - Otherwise, the function uses ``guild.members``; if that list is not
      available (e.g., minimal member cache), ``None`` is returned so the
      caller can choose to skip user pruning.
    """
    if member_ids is not None:
        return {int(member_id) for member_id in member_ids}

    members = getattr(guild, "members", None)
    if not members:
        return None
    return {int(member.id) for member in members}
