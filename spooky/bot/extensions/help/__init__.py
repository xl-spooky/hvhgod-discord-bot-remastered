"""Help command extension."""

from __future__ import annotations

from spooky.bot import Spooky

from .commands import HelpCommands


def setup(bot: Spooky) -> None:
    """Register the help command cog."""
    bot.add_cog(HelpCommands(bot))
