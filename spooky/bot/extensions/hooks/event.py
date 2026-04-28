"""Lifecycle event listeners for the hooks extension package.

This module logs high-level startup milestones and performs global teardown
of UI views when their associated messages are deleted. The cleanup process
is fully automatic and does not require views to register themselves; all
synchronization is handled through disnakes internal view store.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import disnake
from disnake.abc import Messageable
from disnake.ext import commands
from loguru import logger
from spooky.bot import Spooky, __author__, __version__
from spooky.core import checks
from spooky.db import get_session
from spooky.ext.components.v2.card import status_card
from spooky.ext.constants import BUYER_ALERT_CHANNEL_ID
from spooky.models.entities.buyers import BuyerChannel
from sqlalchemy import select

__all__ = ["LifecycleEvents"]


class LifecycleEvents(commands.Cog):
    """Listeners for lifecycle and housekeeping events.

    This cog centralizes operational lifecycle hooks such as startup logging
    and global teardown of active UI views. When messages are removed—
    individually or in bulk—the internal disnake view store is inspected
    and any associated running views are stopped to ensure no orphaned
    component handlers remain active.
    """

    def __init__(self, bot: Spooky) -> None:
        """Cache bot metadata for formatted status output.

        Parameters
        ----------
        bot:
            The active :class:`~spooky.bot.Spooky` instance.
        """
        self.bot = bot
        self._version: str = getattr(bot, "__version__", __version__)
        self._developers: str = getattr(bot, "__developers__", __author__)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Log a readiness milestone once the bot reports it is ready."""
        logger.info(
            "Spooky bot ready! version={} developers={}",
            self._version,
            self._developers,
        )
        await self._run_buyer_departure_db_sync()

    async def _send_buyer_departure_warning(
        self,
        *,
        user_id: int,
        channel_id: int | None = None,
        source: str,
    ) -> None:
        """Publish a warning card for a buyer that left while having a channel row."""
        alert_channel = self.bot.get_channel(BUYER_ALERT_CHANNEL_ID)
        if not isinstance(alert_channel, Messageable):
            logger.warning(
                "Unable to resolve buyer alert channel {}",
                BUYER_ALERT_CHANNEL_ID,
            )
            return

        channel_text = f"<#{channel_id}>" if channel_id is not None else "`unknown`"
        await alert_channel.send(
            embed=status_card(
                None,
                (
                    f"⚠️ Buyer <@{user_id}> (`{user_id}`) appears to have left the server. "
                    f"Stored buyer channel: {channel_text}. "
                    f"Detection source: `{source}`."
                ),
                ensure_period=False,
            )
        )

    async def _run_buyer_departure_db_sync(self) -> None:
        """Re-check persisted buyer rows against guild membership after startup."""
        if not checks.db_enabled():
            return

        async with get_session() as session:
            rows = (await session.execute(select(BuyerChannel))).scalars().all()

        if not rows:
            return

        notified_pairs: set[tuple[int, int]] = set()
        for row in rows:
            channel = self.bot.get_channel(int(row.channel_id))
            if not isinstance(channel, disnake.abc.GuildChannel | disnake.Thread):
                continue

            guild = channel.guild
            if guild.get_member(int(row.user_id)) is not None:
                continue

            dedupe_key = (int(row.user_id), int(row.channel_id))
            if dedupe_key in notified_pairs:
                continue
            notified_pairs.add(dedupe_key)
            await self._send_buyer_departure_warning(
                user_id=int(row.user_id),
                channel_id=int(row.channel_id),
                source="db_sync:on_ready",
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: disnake.Member) -> None:
        """Notify operations when a buyer with stored channel records leaves."""
        if not checks.db_enabled():
            return

        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        select(BuyerChannel).where(BuyerChannel.user_id == int(member.id))
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            return

        for row in rows:
            await self._send_buyer_departure_warning(
                user_id=int(member.id),
                channel_id=int(row.channel_id),
                source="event:on_member_remove",
            )

    def _stop_views_for_message_ids(self, message_ids: Iterable[int]) -> None:
        """Stop UI views associated with the given deleted message IDs.

        Disnake tracks all running views inside its internal view store. This
        helper synchronizes that store with raw gateway deletes by stopping
        any views registered for messages that were removed. This ensures:
        - active components do not remain listening after deletion,
        - cleanup works even when messages were never cached,
        - panels and interactive UIs terminate cleanly.

        Parameters
        ----------
        message_ids:
            Iterable of message IDs whose associated UI views should be
            stopped and detached from the internal view store.
        """
        state = getattr(self.bot, "_connection", None)
        if state is None:
            return

        view_store = getattr(state, "_view_store", None)
        if view_store is None:
            return

        remove_tracking = getattr(view_store, "remove_message_tracking", None)
        synced = getattr(view_store, "_synced_message_views", None)

        for message_id in message_ids:
            view: disnake.ui.View | None = None

            try:
                if callable(remove_tracking):
                    # Disnake-native: remove view tracking and return the view.
                    view = cast(disnake.ui.View | None, remove_tracking(message_id))
                elif isinstance(synced, dict):
                    # Fallback: manually remove from the synced view mapping.
                    view = cast(disnake.ui.View | None, synced.pop(message_id, None))
            except Exception as exc:
                logger.opt(exception=exc).warning(
                    "Failed detaching view tracking for message_id={}", message_id
                )
                continue

            if view is None:
                continue

            try:
                view.stop()
            except Exception as exc:
                logger.opt(exception=exc).warning(
                    "Failed stopping UI view for deleted message_id={}", message_id
                )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self,
        payload: disnake.RawMessageDeleteEvent,
    ) -> None:
        """Stop any UI views associated with a deleted message.

        Raw delete events are triggered even when the original message is not
        cached, making them reliable for cleaning up long-lived views. This
        listener extracts the deleted message ID and delegates cleanup to
        :meth:`_stop_views_for_message_ids`.

        Parameters
        ----------
        payload:
            Raw gateway payload containing the deleted message ID and guild
            context. The message object itself may be missing from cache.
        """
        self._stop_views_for_message_ids([payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(
        self,
        payload: disnake.RawBulkMessageDeleteEvent,
    ) -> None:
        """Stop all UI views associated with messages removed in bulk.

        Bulk delete events can correspond to large-scale moderation actions
        or message pruning operations, and may span dozens or hundreds of
        messages. All associated UI views must be safely terminated to avoid
        dangling component handlers.

        Parameters
        ----------
        payload:
            Raw gateway payload containing a sequence of deleted message IDs
            and contextual guild information. Message objects may not be in
            cache, so IDs are used directly.
        """
        self._stop_views_for_message_ids(payload.message_ids)
