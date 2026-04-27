"""Custom context utilities for Spooky message commands.

This module defines :class:`SpookyContext`, the default :mod:`disnake.ext.commands`
context used for **prefix (message) commands** executed by
:class:`spooky.bot.Spooky`. It adds ergonomic helpers for sending consistently
styled **status embeds** (success, warning, error) that mirror the bot's
"report card" visuals provided by :func:`spooky.ext.components.v2.card.status_card`.

Usage
-----
Subclass your bot from :class:`commands.Bot` (or your own Spooky bot class)
and set its ``context`` type to :class:`SpookyContext`, or cast the context in
your command callbacks. Then call :meth:`SpookyContext.approve`,
:meth:`SpookyContext.warning`, or :meth:`SpookyContext.error` to send
standardized embeds.

Examples
--------
>>> @bot.command()
... async def ping(ctx: SpookyContext):
...     await ctx.approve("Pong!")

"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import disnake
from disnake.ext import commands
from spooky.ext.components.v2.card import status_card

__all__ = ["SpookyContext"]


@lru_cache(maxsize=1)
def _get_status_card() -> Callable[..., disnake.Embed]:
    """Return the cached status-card factory.

    This lazily imports :func:`spooky.ext.components.v2.card.status_card`
    to avoid import-time cycles and caches the callable (single entry) for
    subsequent use by :class:`SpookyContext` helpers.

    Returns
    -------
    Callable[..., disnake.Embed]
        A function compatible with ``status_card(success, description, *,
        ensure_period=True)`` that produces a themed :class:`disnake.Embed`.
    """
    return status_card


class SpookyContext(commands.Context[Any]):
    """Context subclass that adds rich, themed status helpers.

    The helpers here standardize success/warning/error embeds so command
    handlers don't need to manually construct styled :class:`disnake.Embed`
    objects. Internally they delegate to the central ``status_card`` factory.

    Notes
    -----
    - All helpers accept ``**kwargs`` that are forwarded verbatim to
      :meth:`disnake.abc.Messageable.send`, allowing attachments, components,
      reference messages, etc.
    - Set ``ensure_period=False`` to keep the ``description`` unchanged.

    """

    async def approve(
        self,
        description: str,
        /,
        *,
        ensure_period: bool = True,
        **kwargs: Any,
    ) -> disnake.Message:
        """Send a **success** card styled like the report card.

        Parameters
        ----------
        description : str
            Main message body displayed in the embed.
        ensure_period : bool, optional
            If ``True`` (default), the description is ensured to end with a period.
        **kwargs : Any
            Forwarded to :meth:`disnake.abc.Messageable.send` (e.g., ``view=``,
            ``files=``, ``reference=``, etc.).

        Returns
        -------
        disnake.Message
            The message created in the channel.
        """
        status_card = _get_status_card()
        embed = status_card(True, description, ensure_period=ensure_period)
        return await self.send(embed=embed, **kwargs)

    async def warning(
        self,
        description: str,
        /,
        *,
        ensure_period: bool = True,
        **kwargs: Any,
    ) -> disnake.Message:
        """Send a **warning/neutral** card styled like the report card.

        Parameters
        ----------
        description : str
            Main message body displayed in the embed.
        ensure_period : bool, optional
            If ``True`` (default), the description is ensured to end with a period.
        **kwargs : Any
            Forwarded to :meth:`disnake.abc.Messageable.send`.

        Returns
        -------
        disnake.Message
            The message created in the channel.
        """
        status_card = _get_status_card()
        embed = status_card(None, description, ensure_period=ensure_period)
        return await self.send(embed=embed, **kwargs)

    async def error(
        self,
        description: str,
        /,
        *,
        ensure_period: bool = True,
        **kwargs: Any,
    ) -> disnake.Message:
        """Send an **error** card styled like the report card.

        Parameters
        ----------
        description : str
            Main message body displayed in the embed.
        ensure_period : bool, optional
            If ``True`` (default), the description is ensured to end with a period.
        **kwargs : Any
            Forwarded to :meth:`disnake.abc.Messageable.send`.

        Returns
        -------
        disnake.Message
            The message created in the channel.
        """
        status_card = _get_status_card()
        embed = status_card(False, description, ensure_period=ensure_period)
        return await self.send(embed=embed, **kwargs)
