"""Telemetry utilities for operational diagnostics and exception reporting.

This module provides lightweight tooling for emitting structured telemetry
messages to a designated Discord channel (e.g., for production monitoring,
crash diagnostics, or critical failure alerts).

Telemetry is designed to be **best-effort and non-intrusive**: failures in logging
should never crash the application or cause cascading exceptions.

Environment
-----------
The following environment variable controls telemetry delivery:
- ``SPOOKY_TELEMETRY_CHANNEL_ID`` : The numeric ID of a target
  :class:`disnake.TextChannel` where telemetry events should be sent.
  If not set, malformed, or unmappable, telemetry silently no-ops.

Key Features
------------
- Minimal overhead during exception paths.
- Optional traceback attachment for deep diagnostics.
- Makes use of existing status card conventions via :func:`status_card`.
- Fully safe: failures in telemetry sending are caught and logged defensively.

Functions
---------
- :func:`send_exception` :
  Send a failure embed and optional traceback file to the telemetry channel.

Typical Usage
-------------
Called from exception-handling code paths:

>>> try:
...     risky_stuff()
... except Exception as exc:
...     await send_exception(
...         bot,
...         title="Unexpected Runtime Error",
...         description=f"While executing task X: {exc}",
...         error=exc,
...     )

Notes
-----
- The embed uses the Spooky project's standard failure styling.
- A ``Traceback.txt`` file is attached only when ``error`` is provided.
- If the channel cannot be resolved or sending fails, the failure is logged
  via :mod:`loguru` and safely ignored to prevent cascading issues.
"""

from __future__ import annotations

import os
import traceback
from io import BytesIO

import disnake
from disnake.ext import commands
from loguru import logger
from spooky.core import messages
from spooky.ext.components.v2.card import status_card
from spooky.ext.truncate import truncate


async def send_exception(
    bot: commands.Bot,
    *,
    title: str,
    description: str,
    error: BaseException | None = None,
) -> None:
    """Send a telemetry embed to the configured telemetry channel, if available.

    This function attempts to resolve the channel defined by
    ``SPOOKY_TELEMETRY_CHANNEL_ID``. When valid and accessible, a standardized
    failure embed is sent, with an optional traceback attachment.

    Parameters
    ----------
    bot : commands.Bot
        The bot instance used to resolve or fetch the telemetry channel.
    title : str
        A short, attention-grabbing summary to display in the embed body.
    description : str
        Additional contextual details (truncated to 1024 characters).
    error : BaseException | None, optional
        When provided, a ``Traceback.txt`` file with the formatted traceback is
        attached to aid postmortem debugging.

    Behavior
    --------
    - If the environment variable is missing or invalid, returns silently.
    - If the channel ID resolves but is not a :class:`disnake.TextChannel`, a
      warning is logged and the function returns.
    - Any errors occurring during channel resolution or message sending are logged
      using :mod:`loguru` but are not re-raised (to avoid cascading failures).

    Notes
    -----
    - Embeds are constructed via :func:`status_card(False, title)`.
    - If :mod:`spooky.core.messages.telemetry.details_title` is missing or invalid,
      a fallback field name with value ``"Details"`` is used.
    - Traceback formatting uses :func:`traceback.format_exception`.

    Examples
    --------
    >>> await send_exception(
    ...     bot,
    ...     title="Unhandled exception in job loop",
    ...     description="Job ID: cleanup_task",
    ...     error=exc,
    ... )
    """
    chan_id_str = os.getenv("SPOOKY_TELEMETRY_CHANNEL_ID")
    if not chan_id_str or not chan_id_str.isdigit():
        return

    channel_id = int(chan_id_str)

    channel: disnake.abc.GuildChannel | disnake.abc.PrivateChannel | disnake.Thread | None = (
        bot.get_channel(channel_id)
    )
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as exc:
            logger.error("Failed to resolve telemetry channel: {}", exc)
            channel = None

    if channel is None:
        logger.error("Telemetry channel not found or inaccessible: {}", channel_id)
        return
    if not isinstance(channel, disnake.TextChannel):
        logger.error("Telemetry channel {} is not a TextChannel", channel_id)
        return

    embed = status_card(False, title)
    if description:
        try:
            details_title: str = messages.telemetry.details_title
        except Exception:
            details_title = "Details"
        embed.add_field(
            name=details_title,
            value=truncate(description, 1024),
            inline=False,
        )

    files: list[disnake.File] = []
    if error is not None:
        trace = "".join(traceback.format_exception(error))
        files.append(disnake.File(BytesIO(trace.encode("utf-8")), filename="Traceback.txt"))

    try:
        await channel.send(embed=embed, files=files)
    except Exception as send_err:  # pragma: no cover - defensive
        logger.error("Failed to send telemetry: {}", send_err)
