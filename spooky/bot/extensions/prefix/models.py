"""Dataclasses and typed helpers for the prefix extension.

This module defines a minimal **context proxy** used to bridge message-based
command invocations with permission utilities that expect interaction-like
objects.

Background
----------
Certain shared helpers—such as :func:`spooky.ext.components.permissions.has_perms_or_override`—
are written to operate on :class:`disnake.Interaction`-compatible structures.
Rather than duplicating logic for message commands, we use a lightweight
dataclass that mimics the subset of attributes those helpers rely on.

Design notes
------------
- The proxy does **not** subclass :class:`disnake.Interaction`; it merely
  provides a consistent attribute interface.
- Only fields required by permission checks are defined (``guild_id``,
  ``guild``, ``author``, and ``bot``).
- No methods or behavior beyond attribute access are implemented; this class is
  intended for short-lived use during permission evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass

import disnake
from spooky.bot import Spooky

__all__ = ["ContextInteractionProxy"]


@dataclass(slots=True)
class ContextInteractionProxy:
    """Lightweight stand-in for :class:`disnake.Interaction` in prefix commands.

    This proxy allows the reuse of interaction-based permission checks within
    standard message-command flows. It provides the minimal fields required by
    :func:`spooky.ext.components.permissions.has_perms_or_override`.

    Attributes
    ----------
    guild_id : int | None
        ID of the guild in which the command was invoked, or ``None`` for DMs.
    guild : disnake.Guild | None
        The guild object corresponding to ``guild_id``.
    author : disnake.Member | disnake.User
        The user who invoked the command. Typically a
        :class:`disnake.Member` inside guilds or a :class:`disnake.User`
        in direct messages.
    bot : Spooky
        The running bot instance, used by permission resolvers and context
        evaluation.
    """

    guild_id: int | None
    guild: disnake.Guild | None
    author: disnake.Member | disnake.User
    bot: Spooky
