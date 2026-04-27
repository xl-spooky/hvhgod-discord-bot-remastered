"""Prefix message command extension."""

from __future__ import annotations

from spooky.bot import Spooky

from .commands import PrefixCommands


def setup(bot: Spooky) -> None:
    """Register the prefix commands cog."""
    bot.add_cog(PrefixCommands(bot))
