"""Hooks extension entry point.

This module initializes process-wide hooks that apply across the bot,
including database synchronization tasks and global error handling.

Registered components
---------------------
- :class:`LifecycleEvents`:
    Logs core lifecycle events (e.g., :event:`disnake.on_ready`) for
    observability and monitoring.
- :class:`SyncDatabase`:
    Maintains database consistency with the bot's current Discord state and
    performs periodic pruning of stale or expired data.
- :class:`ErrorHandler`:
    Global slash-command error listener that provides consistent exception
    handling, logging, and user feedback.

Usage
-----
This module is loaded via the bot's standard extension mechanism. The
:func:`setup` function is called by the extension loader to register cogs.

Example
-------
>>> bot.load_extension("spooky.bot.extensions.hooks")
"""

from __future__ import annotations

from spooky.bot import Spooky

from .db_sync import SyncDatabase
from .error_handler import ErrorHandler
from .event import LifecycleEvents


def setup(bot: Spooky) -> None:
    """Register the cogs provided by this hooks package.

    Parameters
    ----------
    bot:
        The running :class:`~spooky.bot.Spooky` instance to which the cogs
        should be added.

    Notes
    -----
    Cogs are added immediately and begin operation: background tasks within
    :class:`SyncDatabase` start on load, and :class:`ErrorHandler` listeners
    become active.
    """
    bot.add_cog(LifecycleEvents(bot))
    bot.add_cog(SyncDatabase(bot))
    bot.add_cog(ErrorHandler(bot))
