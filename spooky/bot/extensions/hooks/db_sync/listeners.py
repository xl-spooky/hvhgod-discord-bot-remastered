"""Guild/member lifecycle DB sync handlers for Spooky.

This module contains small, **idempotent** helpers that keep database rows in
sync with Discord guild/member lifecycle events. They are designed to be called
from your event listeners (e.g., ``on_guild_join`` / ``on_raw_member_remove``)
and are **DB-aware**: if the database is disabled (see
:func:`spooky.core.checks.db_enabled`), they return immediately without side
effects.

Responsibilities
----------------
- Ensure core rows exist when the bot joins a guild or a member joins
  (``Guild``, ``User`` via :func:`fetch_db_guild` / :func:`fetch_db_user`).
- Clean up per-guild artifacts when the bot is removed (snipe data/config).
- Clean up per-guild user opt-out rows when a member leaves.
- Report unexpected failures to telemetry via :func:`spooky.core.telemetry.send_exception`.

Notes
-----
- All functions are **best-effort**: unexpected errors are logged and reported
  to telemetry but will not raise to callers (defensive paths are marked with
  ``# pragma: no cover``).
- Use these helpers inside your cog/listener implementations to centralize DB
  logic and keep event handlers minimal.
"""

from __future__ import annotations

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.core import checks
from spooky.core.telemetry import send_exception
from spooky.db.errors import handle_db_capacity_error
from spooky.models.utils import fetch_db_guild, fetch_db_user

from .features import auto, command_gate, logging, moderation, owners, permissions, snipe


async def on_guild_join_impl(bot: Spooky, guild: disnake.Guild) -> None:
    """Ensure a :class:`Guild <spooky.models.base_models.guild.Guild>` row exists on join.

    When the bot joins a guild and database features are enabled, this function
    ensures the corresponding ``Guild`` row exists (creating it if missing).

    Parameters
    ----------
    bot : Spooky
        The running bot instance (used for telemetry on failure).
    guild : disnake.Guild
        The guild that the bot just joined.

    Notes
    -----
    - No-ops when :func:`spooky.core.checks.db_enabled` is ``False``.
    - On failure, logs a warning and emits telemetry with the guild ID.
    """
    if not checks.db_enabled():
        return
    try:
        await fetch_db_guild(guild.id)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Failed to ensure guild on join {guild.id}: {e}")
        await send_exception(
            bot,
            title="DB Sync: failed to ensure guild on join",
            description=f"guild={guild.id}",
            error=e,
        )


async def on_guild_remove_impl(bot: Spooky, guild: disnake.Guild) -> None:
    """Delete guild-scoped artifacts when the bot is removed from a guild.

    Removes the guild row and all associated snipe-related data/config (where
    applicable) to keep the database tidy.

    Parameters
    ----------
    bot : Spooky
        The running bot instance (passed to cleanup helpers/telemetry).
    guild : disnake.Guild
        The guild from which the bot was removed.

    Notes
    -----
    - No-ops when :func:`spooky.core.checks.db_enabled` is ``False``.
    - Cleanup is delegated to :func:`.features.snipe.delete_guild_artifacts`.
    """
    if not checks.db_enabled():
        return
    await command_gate.delete_guild_artifacts(bot, guild.id)
    await owners.delete_guild_artifacts(bot, guild.id)
    await auto.delete_guild_artifacts(bot, guild.id)
    await snipe.delete_guild_artifacts(bot, guild.id)


async def on_member_join_impl(bot: Spooky, member: disnake.Member) -> None:
    """Ensure a :class:`User <spooky.models.base_models.user.User>` row exists on member join.

    Parameters
    ----------
    bot : Spooky
        The running bot instance (used for telemetry on failure).
    member : disnake.Member
        The member that just joined the guild.

    Notes
    -----
    - No-ops when :func:`spooky.core.checks.db_enabled` is ``False``.
    - On failure, logs a warning and emits telemetry with user & guild IDs.
    """
    if not checks.db_enabled():
        return
    try:
        await fetch_db_user(member.id)
    except Exception as e:  # pragma: no cover - defensive
        if handle_db_capacity_error(e, context=f"ensuring user on join {member.id}"):
            return

        logger.warning("Failed to ensure user on join {}: {}", member.id, e)
        await send_exception(
            bot,
            title="DB Sync: failed to ensure user on join",
            description=f"user={member.id} guild={member.guild.id}",
            error=e,
        )


async def on_raw_member_remove_impl(
    bot: Spooky, payload: disnake.RawGuildMemberRemoveEvent
) -> None:
    """Clean up per-guild snipe **opt-out** when a member leaves a guild.

    Parameters
    ----------
    bot : Spooky
        The running bot instance (forwarded to telemetry helper).
    payload : disnake.RawGuildMemberRemoveEvent
        Raw payload containing the user and guild identifiers.

    Notes
    -----
    - No-ops when :func:`spooky.core.checks.db_enabled` is ``False``.
    - Delegates cleanup to feature helpers to remove per-guild artifacts
      tied to the departing member.
    """
    if not checks.db_enabled():
        return

    guild_id = int(payload.guild_id)
    user_id = int(payload.user.id)

    await snipe.delete_user_opt_out(bot, guild_id, user_id)
    await command_gate.delete_user_overrides(bot, guild_id, user_id)
    await moderation.delete_user_thresholds(bot, guild_id, user_id)
    await permissions.delete_user_overrides(bot, guild_id, user_id)
    await owners.delete_user_authorization(bot, guild_id, user_id)


async def on_guild_role_delete_impl(bot: Spooky, role: disnake.Role) -> None:
    """Clean up command role overrides when ``role`` is deleted."""
    if not checks.db_enabled():
        return

    await command_gate.delete_role_overrides(bot, role.guild.id, role.id)
    await moderation.delete_role_thresholds(bot, role.guild.id, role.id)


async def on_guild_channel_delete_impl(bot: Spooky, channel: disnake.abc.GuildChannel) -> None:
    """Clean up logging settings if the configured channel is removed."""
    if not checks.db_enabled():
        return

    await logging.prune_channel_targets(bot, channel)
    await auto.prune_channel_configs(bot, channel)


async def on_webhooks_update_impl(bot: Spooky, channel: disnake.abc.GuildChannel) -> None:
    """Clean up logging settings when a channel's webhooks are removed."""
    if not checks.db_enabled():
        return

    if isinstance(channel, (disnake.TextChannel, disnake.NewsChannel)):
        await logging.prune_missing_webhooks(bot, channel)
