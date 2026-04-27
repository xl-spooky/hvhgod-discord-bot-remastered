"""Cleanup task implementations for the DB sync pipeline.

This module provides the concrete implementations for high-level background
jobs invoked by :mod:`tasks.py`. It handles:

- Pruning stale guild rows and related feature data.
- Cleaning command gating overrides and snipe opt-outs for departed members.
- Purging expired snipe entries on a schedule.

All destructive operations use :func:`safe_delete`, which wraps execution,
telemetry, and error handling. Operations requiring DB readiness are
short-circuited by :func:`guard_db_ready`.
"""

from __future__ import annotations

import contextlib

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.ext.time import utcnow
from spooky.models import Guild as GuildModel
from spooky.premium.auto_perks import reconcile_auto_perks

from .features import auto, command_gate, logging, moderation, owners, permissions, premium, snipe
from .utils import guard_db_ready, safe_delete


async def sync_current_guilds_impl(bot: Spooky) -> None:
    """Prune guild-scoped rows that no longer match the bot's presence.

    Workflow
    --------
    1. Abort early if the database is not ready.
    2. Collect the set of guild IDs the bot is currently in.
    3. Remove any ``Guild`` rows not part of that set.
    4. Cascade prune feature data (command gating, snipe tables).

    Parameters
    ----------
    bot:
        Running :class:`~spooky.bot.Spooky` instance providing access to
        cached guilds and telemetry context.

    Notes
    -----
    - This function only **deletes** stale rows. Guild creation is handled by
      runtime listeners (e.g.,
      :func:`spooky.bot.extensions.hooks.db_sync.listeners.on_guild_join_impl`).
    - All prunes log descriptive titles and counts for auditability.
    """
    if not await guard_db_ready(bot):
        return

    logger.info("-- Pruning guild rows against current guild list")
    current_ids: set[int] = {g.id for g in bot.guilds}

    if not current_ids:
        logger.info("No guilds to prune against; deleting all guild-scoped rows")
        deleted = await safe_delete(
            bot,
            GuildModel,
            title="DB Sync: prune all guild rows",
            description="Empty current guilds snapshot",
        )
        logger.info("Guild prune summary: kept={} deleted={}", 0, deleted or 0)

        gate_summary = await command_gate.prune_missing_guilds(bot, [])
        logger.info(
            "Command gate missing guild summary: kept={} disables_deleted={} "
            "roles_deleted={} users_deleted={}",
            gate_summary.kept_guilds,
            gate_summary.disables_deleted,
            gate_summary.role_deleted,
            gate_summary.user_deleted,
        )

        permission_summary = await permissions.prune_missing_guilds(bot, [])
        logger.info(
            "Permissions missing guild summary: kept={} overrides_deleted={}",
            permission_summary.kept_guilds,
            permission_summary.overrides_deleted,
        )

        snipe_summary = await snipe.prune_missing_guilds(bot, [])
        logger.info(
            "Snipe missing guild summary: kept={} messages_deleted={} "
            "edits_deleted={} stickers_deleted={} opt_outs_deleted={} settings_deleted={}",
            snipe_summary.kept_guilds,
            snipe_summary.messages_deleted,
            snipe_summary.edits_deleted,
            snipe_summary.stickers_deleted,
            snipe_summary.opt_out_deleted,
            snipe_summary.settings_deleted,
        )

        moderation_summary = await moderation.prune_missing_guilds(bot, [])
        logger.info(
            "Moderation missing guild summary: kept={} actions_deleted={} thresholds_deleted={} "
            "usage_deleted={}",
            moderation_summary.kept_guilds,
            moderation_summary.actions_deleted,
            moderation_summary.thresholds_deleted,
            moderation_summary.usage_deleted,
        )

        owners_summary = await owners.prune_missing_guilds(bot, [])
        logger.info(
            (
                "Owner authorization missing guild summary: kept={} authorizations_deleted={} "
                "access_deleted={}"
            ),
            owners_summary.kept_guilds,
            owners_summary.authorizations_deleted,
            owners_summary.access_deleted,
        )

        auto_summary = await auto.prune_missing_guilds(bot, [])
        logger.info(
            "Auto nuke missing guild summary: kept={} configs_deleted={}",
            auto_summary.kept_guilds,
            auto_summary.configs_deleted,
        )

        channel_summary = await auto.prune_missing_channels(bot)
        logger.info(
            "Auto nuke missing channel summary: checked_guilds={} configs_deleted={}",
            channel_summary.checked_guilds,
            channel_summary.configs_deleted,
        )
        return

    # Prune stale Guild rows and associated feature rows
    deleted = await safe_delete(
        bot,
        GuildModel,
        GuildModel.id.notin_(list(current_ids)),
        title="DB Sync: prune stale guild rows",
        description=f"kept_guilds={len(current_ids)}",
    )
    logger.info("Guild prune summary: kept={} deleted={}", len(current_ids), deleted or 0)

    gate_summary = await command_gate.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Command gate missing guild summary: kept={} disables_deleted={} "
        "roles_deleted={} users_deleted={}",
        gate_summary.kept_guilds,
        gate_summary.disables_deleted,
        gate_summary.role_deleted,
        gate_summary.user_deleted,
    )

    permission_summary = await permissions.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Permissions missing guild summary: kept={} overrides_deleted={}",
        permission_summary.kept_guilds,
        permission_summary.overrides_deleted,
    )

    snipe_summary = await snipe.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Snipe missing guild summary: kept={} messages_deleted={} "
        "edits_deleted={} stickers_deleted={} opt_outs_deleted={} settings_deleted={}",
        snipe_summary.kept_guilds,
        snipe_summary.messages_deleted,
        snipe_summary.edits_deleted,
        snipe_summary.stickers_deleted,
        snipe_summary.opt_out_deleted,
        snipe_summary.settings_deleted,
    )

    logging_summary = await logging.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Logging missing guild summary: kept={} settings_deleted={}",
        logging_summary.kept_guilds,
        logging_summary.settings_deleted,
    )

    moderation_summary = await moderation.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Moderation missing guild summary: kept={} actions_deleted={} thresholds_deleted={} "
        "usage_deleted={}",
        moderation_summary.kept_guilds,
        moderation_summary.actions_deleted,
        moderation_summary.thresholds_deleted,
        moderation_summary.usage_deleted,
    )

    owners_summary = await owners.prune_missing_guilds(bot, current_ids)
    logger.info(
        (
            "Owner authorization missing guild summary: kept={} authorizations_deleted={} "
            "access_deleted={}"
        ),
        owners_summary.kept_guilds,
        owners_summary.authorizations_deleted,
        owners_summary.access_deleted,
    )

    auto_summary = await auto.prune_missing_guilds(bot, current_ids)
    logger.info(
        "Auto nuke missing guild summary: kept={} configs_deleted={}",
        auto_summary.kept_guilds,
        auto_summary.configs_deleted,
    )

    channel_summary = await auto.prune_missing_channels(bot)
    logger.info(
        "Auto nuke missing channel summary: checked_guilds={} configs_deleted={}",
        channel_summary.checked_guilds,
        channel_summary.configs_deleted,
    )

    await logging.reconcile_logging_targets(bot)

    unban_summary = await moderation.reconcile_unbans(bot)
    logger.info(
        "Moderation unban reconciliation summary: guilds={} skipped={} checked={} deleted={}",
        unban_summary.guilds_processed,
        unban_summary.guilds_skipped,
        unban_summary.active_bans_checked,
        unban_summary.actions_removed,
    )


async def _resolve_member_ids(guild: disnake.Guild) -> set[int] | None:
    """Return a best-effort snapshot of member IDs for ``guild``.

    This helper tries cached members first, then falls back to chunking,
    and finally to an API fetch when available. It keeps DB sync routines
    resilient even when the bot starts before member chunking finishes.
    """
    members = getattr(guild, "members", None)
    member_count = getattr(guild, "member_count", None)
    if members and (member_count is None or len(members) >= member_count):
        return {int(member.id) for member in members}

    with contextlib.suppress(Exception):
        chunked = await guild.chunk(cache=True)
        if chunked and (member_count is None or len(chunked) >= member_count):
            return {int(member.id) for member in chunked}

    with contextlib.suppress(Exception):
        fetched = await guild.fetch_members(limit=None).flatten()
        if fetched and (member_count is None or len(fetched) >= (member_count or len(fetched))):
            return {int(member.id) for member in fetched}

    return None


async def sync_current_users_impl(bot: Spooky) -> None:
    """Prune per-guild artifacts for members no longer cached.

    Workflow
    --------
    1. Abort if the database is not ready.
    2. Iterate through all cached guilds and collect member IDs (chunking when necessary).
    3. Delete command gating overrides and snipe opt-outs tied to missing members.

    Parameters
    ----------
    bot:
        Running :class:`~spooky.bot.Spooky` instance providing access to
        cached guilds, members, and telemetry context.

    Notes
    -----
    - This routine only removes stale overrides/opt-outs; creation remains handled
      by event-driven listeners.
    - If members cannot be resolved for a guild, role overrides are still pruned
      but user-focused deletions are skipped until better data is available.
    """
    if not await guard_db_ready(bot):
        return

    logger.info(
        "-- Pruning command overrides, thresholds, permissions,"
        " and snipe opt-outs for cached guilds",
    )

    gate_processed = 0
    gate_skipped = 0
    gate_roles_deleted = 0
    gate_user_candidates = 0
    gate_users_deleted = 0

    snipe_processed = 0
    snipe_skipped = 0
    snipe_evaluated = 0
    snipe_stale = 0
    snipe_deleted = 0

    threshold_processed = 0
    threshold_skipped = 0
    threshold_roles_deleted = 0
    threshold_users_deleted = 0

    permission_processed = 0
    permission_skipped = 0
    permission_deleted = 0

    owner_processed = 0
    owner_skipped = 0
    owner_deleted = 0

    for guild in bot.guilds:
        member_ids = await _resolve_member_ids(guild)

        gate_summary = await command_gate.prune_guild_targets(bot, guild, member_ids=member_ids)
        gate_processed += 1
        gate_roles_deleted += gate_summary.role_deleted
        gate_user_candidates += gate_summary.stale_user_candidates
        gate_users_deleted += gate_summary.user_deleted
        if gate_summary.skipped_user_prune:
            gate_skipped += 1

        threshold_summary = await moderation.prune_threshold_targets(
            bot, guild, member_ids=member_ids
        )
        threshold_processed += 1
        threshold_roles_deleted += threshold_summary.role_deleted
        threshold_users_deleted += threshold_summary.user_deleted
        if threshold_summary.skipped_user_prune:
            threshold_skipped += 1

        permission_summary = await permissions.prune_guild_targets(
            bot, guild, member_ids=member_ids
        )
        permission_processed += 1
        permission_deleted += permission_summary.overrides_deleted
        if permission_summary.skipped_user_prune:
            permission_skipped += 1

        owner_summary = await owners.prune_guild_members(bot, guild, member_ids=member_ids)
        owner_processed += 1
        owner_deleted += owner_summary.deleted
        if owner_summary.skipped_user_prune:
            owner_skipped += 1

        opt_out_summary = await snipe.prune_missing_opt_outs(bot, guild, member_ids=member_ids)
        snipe_processed += 1
        snipe_evaluated += opt_out_summary.evaluated
        snipe_stale += opt_out_summary.stale
        snipe_deleted += opt_out_summary.deleted
        if opt_out_summary.skipped_user_prune:
            snipe_skipped += 1

    logger.info(
        (
            "Command gate summary: guilds={} skipped={} roles_deleted={} "
            "user_candidates={} users_deleted={}"
        ),
        gate_processed,
        gate_skipped,
        gate_roles_deleted,
        gate_user_candidates,
        gate_users_deleted,
    )
    logger.info(
        ("Moderation thresholds summary: guilds={} skipped={} roles_deleted={} users_deleted={}"),
        threshold_processed,
        threshold_skipped,
        threshold_roles_deleted,
        threshold_users_deleted,
    )
    logger.info(
        "Permissions summary: guilds={} skipped={} overrides_deleted={}",
        permission_processed,
        permission_skipped,
        permission_deleted,
    )
    logger.info(
        "Owner authorization summary: guilds={} skipped={} authorizations_deleted={}",
        owner_processed,
        owner_skipped,
        owner_deleted,
    )
    logger.info(
        ("Snipe summary: guilds={} skipped={} evaluated={} stale_candidates={} deleted={}"),
        snipe_processed,
        snipe_skipped,
        snipe_evaluated,
        snipe_stale,
        snipe_deleted,
    )


async def sync_premium_entitlements_impl(bot: Spooky) -> None:
    """Ensure premium entitlements are reconciled after downtime."""
    if not await guard_db_ready(bot):
        return

    await premium.sync_entitlements(bot)
    removed = await reconcile_auto_perks(bot)
    if removed:
        logger.info("Removed {} auto configs while enforcing free-tier limits", removed)


async def delete_expired_snipe_impl(bot: Spooky) -> None:
    """Purge all snipe entries whose expiration timestamp has passed.

    Parameters
    ----------
    bot:
        Running :class:`~spooky.bot.Spooky` instance.

    Notes
    -----
    - Uses :func:`delete_expired_entries` with the current UTC timestamp.
    - No deletions occur if the DB fails readiness checks.
    """
    if not await guard_db_ready(bot):
        return

    logger.info("-- Cleaning up expired snipe entries")
    now = utcnow()

    summary = await snipe.delete_expired_entries(bot, reference_time=now)
    logger.info(
        "Snipe expiration summary: messages_deleted={} edits_deleted={} stickers_deleted={}",
        summary.messages_deleted,
        summary.edits_deleted,
        summary.stickers_deleted,
    )


async def enforcement_cycle_impl(bot: Spooky) -> None:
    """Run 5-minute enforcement tasks (expired bans + auto nukes)."""
    if not await guard_db_ready(bot):
        return

    logger.info("-- Running enforcement cycle tasks (5 minutes)")
    now = utcnow()

    summary = await moderation.release_expired_bans(bot, reference_time=now)
    logger.info(
        "Moderation ban expiration summary: processed={} succeeded={} failed={} skipped={}",
        summary.processed,
        summary.succeeded,
        summary.failed,
        summary.skipped,
    )

    auto_summary = await auto.process_due_nukes(bot, reference_time=now)
    logger.info(
        "Auto nuke summary: processed={} succeeded={} failed={} dropped={}",
        auto_summary.processed,
        auto_summary.succeeded,
        auto_summary.failed,
        auto_summary.dropped,
    )


async def entity_cleaner_impl(bot: Spooky) -> None:
    """Global cleanup task for expired moderation entities."""
    if not await guard_db_ready(bot):
        return

    logger.info("-- Pruning expired moderation entities")
    now = utcnow()

    removed_usage = await moderation.delete_expired_command_usage(bot, reference_time=now)
    logger.info("Moderation entity cleaner summary: expired_usage_deleted={}", removed_usage)

    removed_auto = await reconcile_auto_perks(bot)
    if removed_auto:
        logger.info("Auto premium reconciliation removed {} configs", removed_auto)
