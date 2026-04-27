"""Helpers for building compact status cards.

This module replaces the legacy ``report_embed`` helper with a more flexible
:func:`status_card` function. Status cards are short embeds that communicate the
result of an action (success, warning, or error) with consistent emoji and
colour conventions across the bot.

Features
--------
- Centralized palette definitions for success, warning, and error
- Consistent emoji and colour usage via :mod:`spooky.core.emojis` and :mod:`spooky.core.colors`
- Optional automatic sentence-final period for cleaner prose
- Minimal surface area to encourage uniform styling across call sites

Example
-------
>>> embed = status_card(True, "Operation completed")
>>> await ctx.send(embed=embed)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import disnake
from disnake import ui
from spooky.core import colors, emojis

__all__ = ["CardPalette", "status_card", "status_container"]


@dataclass(slots=True)
class CardPalette:
    """Visual palette used when rendering a status card.

    A palette bundles the emoji prefix and the border colour used by the
    resulting :class:`disnake.Embed`. Palettes are mapped to semantic outcomes
    (success, warning/neutral, error) to keep visual language consistent.

    Attributes
    ----------
    emoji : str
        Emoji displayed before the description text (e.g., a checkmark or warning symbol).
    colour : disnake.Colour
        Embed accent/border colour applied to the status card.
    """

    emoji: str
    colour: disnake.Colour


SUCCESS: Final[CardPalette] = CardPalette(
    emoji=emojis.checkmark,
    colour=disnake.Colour(colors.green),
)
WARNING: Final[CardPalette] = CardPalette(
    emoji=emojis.warning,
    colour=disnake.Colour(colors.yellow),
)
ERROR: Final[CardPalette] = CardPalette(
    emoji=emojis.error,
    colour=disnake.Colour(colors.red),
)


def status_card(
    success: bool | None,
    description: str,
    *,
    ensure_period: bool = True,
) -> disnake.Embed:
    """Return a short status embed aligned with the project's visual language.

    The palette is derived from ``success``:
      - ``True`` → success palette (:data:`SUCCESS`)
      - ``False`` → error palette (:data:`ERROR`)
      - ``None`` → warning/neutral palette (:data:`WARNING`)

    If ``ensure_period`` is enabled and the description ends with an alphanumeric
    character, a period is appended for grammatical consistency.

    Parameters
    ----------
    success :
        ``True`` for success, ``False`` for failure, ``None`` for neutral/warning.
    description :
        Plain-text body of the card. A trailing period may be appended when
        ``ensure_period`` is true and the description ends with an alphanumeric
        character.
    ensure_period :
        When ``True`` (default), append a trailing period when the description ends
        with an alphanumeric character. Disable when the caller wants to control
        punctuation manually.

    Returns
    -------
    disnake.Embed
        A compact embed containing the emoji prefix, formatted description, and
        palette-derived colour.

    Notes
    -----
    Keep messages succinct—status cards are intended for one-line summaries.
    """
    palette = SUCCESS if success else ERROR if success is False else WARNING

    if ensure_period and description and description[-1].isalnum():
        description += "."

    return disnake.Embed(description=f"{palette.emoji} | {description}", colour=palette.colour)


def status_container(
    success: bool | None,
    description: str,
    *,
    ensure_period: bool = True,
) -> ui.Container:
    """Build a UI container that visually represents a status message.

    This function wraps :func:`status_card` to create a compact
    :class:`ui.Container` displaying the status description using
    :class:`ui.TextDisplay`, styled with the embeds accent colour.
    It is typically used in UI flows where a small status block is
    preferred over a full embed.

    Parameters
    ----------
    success:
        The overall outcome indicator:
        - ``True`` for success,
        - ``False`` for failure,
        - ``None`` for a neutral/unknown state.
    description:
        The human-readable message describing the status.
    ensure_period:
        Whether a trailing period should be enforced in the final
        description passed to :func:`status_card`. Defaults to ``True``.

    Returns
    -------
    ui.Container
        A container embedding the formatted status text and accent colour.
    """
    embed = status_card(success, description, ensure_period=ensure_period)
    text = embed.description or ""
    return ui.Container(
        ui.TextDisplay(text),
        accent_colour=embed.colour,
    )
