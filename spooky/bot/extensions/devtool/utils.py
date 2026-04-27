"""Utility helpers for developer-only command execution.

This module contains lightweight asynchronous helpers used by the developer
command suite to validate context and authorization before command execution.
They ensure that privileged commands can only be invoked within the internal
developer guild and by approved maintainers.

Usage
-----
These utilities are typically invoked by :meth:`DevTools.cog_check` or similar
authorization hooks::

    from spooky.bot.extensions.devtool.utils import ensure_developer_context

    @commands.slash_command()
    async def restricted(inter):
        if not await ensure_developer_context(inter):
            return
        ...

Notes
-----
- The validation routine provides in-place feedback via ephemeral responses.
- Both guild and user authorization checks must pass for a context to qualify.
"""

from __future__ import annotations

import disnake
from spooky.bot import Spooky

from .constants import DEVELOPER_GUILD_ID, DEVELOPER_IDS

__all__ = ["ensure_developer_context"]


async def ensure_developer_context(inter: disnake.GuildCommandInteraction[Spooky]) -> bool:
    """Ensure that the invoking interaction originates from an authorized context.

    Parameters
    ----------
    inter:
        The active :class:`~disnake.GuildCommandInteraction` to validate.

    Returns
    -------
    bool
        ``True`` if the interaction originates from the developer guild and
        the invoking user is in :data:`~.DEVELOPER_IDS`, otherwise ``False``.

    Notes
    -----
    - Sends an ephemeral feedback message if validation fails.
    - Intended to be used as a guard for restricted commands or cogs.
    """
    if inter.guild_id != DEVELOPER_GUILD_ID:
        if not inter.response.is_done():
            await inter.response.send_message(
                "Developer tools are only available in the developer guild.",
                ephemeral=True,
            )
        return False

    if inter.author.id not in DEVELOPER_IDS:
        if not inter.response.is_done():
            await inter.response.send_message(
                "You are not permitted to use developer tooling commands.",
                ephemeral=True,
            )
        return False

    return True
