"""Hooks extension entry point."""

from __future__ import annotations

from spooky.bot import Spooky

from .event import LifecycleEvents


def setup(bot: Spooky) -> None:
    """Register minimal lifecycle hooks."""
    bot.add_cog(LifecycleEvents(bot))
