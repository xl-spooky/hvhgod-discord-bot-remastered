"""Hooks extension entry point."""

from __future__ import annotations

from spooky.bot import Spooky

from .error_handler import ErrorHandler
from .event import LifecycleEvents


def setup(bot: Spooky) -> None:
    """Register minimal lifecycle hooks."""
    bot.add_cog(LifecycleEvents(bot))
    bot.add_cog(ErrorHandler(bot))
