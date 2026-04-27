"""Database synchronizer package.

This package replaces the previous monolithic ``db_sync.py`` and organizes the
database synchronization logic into focused modules:

- ``tasks.py``: background jobs (bulk sync, periodic cleanup)
- ``listeners.py``: event-driven ensures / cleanup (guilds, members)
- ``utils.py``: shared helpers (guards, safe cancellation)
- ``features/``: feature-specific cleanup logic (e.g., snipe data)

It exports the :class:`SyncDatabase` cog so existing imports like
``from .db_sync import SyncDatabase`` continue to work.

Responsibilities
----------------
- Ensure database rows exist for currently connected guilds and members.
- Periodically prune / cleanup feature-specific data (e.g., expired snipe rows).
- React to Discord events to keep DB state consistent in near-real time.

Scheduling
----------
 - ``sync_current_guilds``: runs once at cog start (``count=1``).
 - ``sync_current_users``: runs once at cog start (``count=1``).
- ``maintenance_cleanup``: runs every 48 hours and combines snipe expiration
  cleanup with moderation entity pruning to avoid redundant scheduling.
 - ``enforcement_cycle``: runs every 5 minutes.

Notes
-----
- All background jobs are safely cancelled in :meth:`cog_unload` using
  :func:`safe_cancel` to avoid leaking tasks during cog reloads.
- This module intentionally contains no ``setup`` function; the cog is imported
  and registered from ``hooks/__init__.py``.
"""

from __future__ import annotations

import disnake
from disnake.ext import commands, tasks as disnake_tasks
from spooky.bot import Spooky

from . import listeners as _listeners, tasks as _tasks
from .utils import safe_cancel

__all__ = ["SyncDatabase"]


class SyncDatabase(commands.Cog):
    """Synchronize the database with Discord entities and perform periodic cleanup.

    This cog wires together:
    - **One-shot startup syncs** for guilds and users, ensuring the DB reflects the
      bot's current presence immediately after the cog is loaded.
    - **Recurring maintenance** to purge feature data that has expired (e.g., snipe artifacts).
    - **Event listeners** that keep the DB in sync as guilds/members join or leave.

    Parameters
    ----------
    bot:
        The running :class:`~spooky.bot.Spooky` instance.

    Lifecycle
    ---------
    On initialization, the background loops are started. When the cog is unloaded,
    all loops are cancelled via :func:`safe_cancel`.

    Attributes
    ----------
    bot:
        The :class:`~spooky.bot.Spooky` client instance used by tasks and listeners.
    """

    def __init__(self, bot: Spooky) -> None:
        self.bot = bot
        self.sync_current_guilds.start()
        self.sync_current_users.start()
        self.sync_premium_entitlements.start()
        self.maintenance_cleanup.start()
        self.enforcement_cycle.start()

    def cog_unload(self) -> None:  # pragma: no cover - safety wrapper
        """Cancel all running loops to prevent task leaks on cog reload/unload."""
        safe_cancel(self.sync_current_guilds)
        safe_cancel(self.sync_current_users)
        safe_cancel(self.sync_premium_entitlements)
        safe_cancel(self.maintenance_cleanup)
        safe_cancel(self.enforcement_cycle)

    @disnake_tasks.loop(count=1)
    async def sync_current_guilds(self) -> None:
        """One-shot startup sync for all currently connected guilds.

        Delegates to :func:`_tasks.sync_current_guilds_impl` to ensure a DB row
        exists for each guild the bot is currently in.

        Notes
        -----
        - Runs exactly once after the cog is initialized (``count=1``).
        - Errors are handled within the implementation for telemetry and resilience.
        """
        await _tasks.sync_current_guilds_impl(self.bot)

    @disnake_tasks.loop(count=1)
    async def sync_current_users(self) -> None:
        """One-shot startup sync for known users/members.

        Delegates to :func:`_tasks.sync_current_users_impl` to upsert user/member
        records as needed.

        Notes
        -----
        - Runs exactly once after the cog is initialized (``count=1``).
        - Scope and performance characteristics are managed by the implementation.
        """
        await _tasks.sync_current_users_impl(self.bot)

    @disnake_tasks.loop(count=1)
    async def sync_premium_entitlements(self) -> None:
        """One-shot premium entitlement reconciliation.

        Ensures that entitlements granted while the bot was offline are
        reflected in the database.
        """
        await _tasks.sync_premium_entitlements_impl(self.bot)

    @disnake_tasks.loop(minutes=5)
    async def enforcement_cycle(self) -> None:
        """Periodic 5-minute enforcement: expired bans and auto nukes."""
        await _tasks.enforcement_cycle_impl(self.bot)

    @disnake_tasks.loop(hours=48)
    async def maintenance_cleanup(self) -> None:
        """Periodic maintenance combining snipe and moderation cleanup.

        This loop merges the previous ``delete_expired_snipe`` and
        ``entity_cleaner`` tasks to reduce redundant scheduling while preserving
        the same cadence.
        """
        await _tasks.delete_expired_snipe_impl(self.bot)
        await _tasks.entity_cleaner_impl(self.bot)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild) -> None:
        """Ensure DB state when the bot joins a guild.

        Parameters
        ----------
        guild:
            The guild that was just joined.
        """
        await _listeners.on_guild_join_impl(self.bot, guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: disnake.Guild) -> None:
        """Cleanup DB state when the bot leaves or is removed from a guild.

        Parameters
        ----------
        guild:
            The guild that was left or removed.
        """
        await _listeners.on_guild_remove_impl(self.bot, guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member) -> None:
        """Ensure DB state for a member who just joined a guild.

        Parameters
        ----------
        member:
            The member that joined.
        """
        await _listeners.on_member_join_impl(self.bot, member)

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload: disnake.RawGuildMemberRemoveEvent) -> None:
        """Cleanup or mark state for a member who left a guild.

        Parameters
        ----------
        payload:
            Raw member remove payload containing the guild and user.
        """
        await _listeners.on_raw_member_remove_impl(self.bot, payload)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: disnake.Role) -> None:
        """Cleanup DB state when a role is deleted from a guild.

        Parameters
        ----------
        role:
            The role that was removed.
        """
        await _listeners.on_guild_role_delete_impl(self.bot, role)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: disnake.abc.GuildChannel) -> None:
        """Cleanup logging settings when a configured channel is removed."""
        await _listeners.on_guild_channel_delete_impl(self.bot, channel)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: disnake.abc.GuildChannel) -> None:
        """Cleanup logging settings when channel webhooks are removed."""
        await _listeners.on_webhooks_update_impl(self.bot, channel)


# No package-level setup function. Import SyncDatabase in hooks/__init__.py and add_cog there.
