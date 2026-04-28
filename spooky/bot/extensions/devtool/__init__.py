"""Developer tooling slash-command extension."""

from __future__ import annotations

from spooky.bot import Spooky

from .commands import DevtoolCommands


def setup(bot: Spooky) -> None:
    """Register developer tooling commands."""
    bot.add_cog(DevtoolCommands(bot))
