"""Developer tooling extension for Spooky internal command suite.

This package exposes the canonical :func:`setup` hook recognized by the bot's
extension loader. Importing :mod:`spooky.bot.extensions.devtools` ensures that
the developer tooling cog is registered on the active
:class:`~spooky.bot.Spooky` instance.

Usage
-----
Load via the bots extension loader::

    >>> bot.load_extension("spooky.bot.extensions.devtools")

Notes
-----
- This extension provides developer-only commands and utilities to aid
  debugging, profiling, and runtime inspection.
- All developer commands are gated behind internal permission checks
  (e.g., owners or maintainers defined in the bot configuration).
- Exceptions raised during cog initialization bubble up to the caller and
  should be logged by the loader.
"""

from __future__ import annotations

from spooky.bot import Spooky

from .commands import DevTools

__all__ = ["setup"]


def setup(bot: Spooky) -> None:
    """Register the developer tooling cog on ``bot``.

    Parameters
    ----------
    bot:
        The running :class:`~spooky.bot.Spooky` instance responsible for
        managing cogs and the command tree.

    Returns
    -------
    None
        This function performs cog registration as a side effect.

    Examples
    --------
    >>> from spooky.bot import Spooky
    >>> bot = Spooky()
    >>> bot.load_extension("spooky.bot.extensions.devtools")  # doctest: +SKIP

    Notes
    -----
    - Registration automatically instantiates :class:`.DevTools`.
    - Errors during initialization are allowed to propagate to the caller
      (e.g., missing dependencies or invalid command declarations).
    - The registration process is idempotent per Disnake semantics.
    """
    bot.add_cog(DevTools(bot))
