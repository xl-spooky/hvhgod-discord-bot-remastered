"""Minimal embed card helpers used by context/telemetry."""

from __future__ import annotations

import disnake
from spooky.core import colors


def status_card(
    success: bool | None,
    description: str,
    *,
    ensure_period: bool = True,
) -> disnake.Embed:
    """Return a simple status embed card.

    Parameters
    ----------
    success : bool | None
        ``True`` for success, ``False`` for error, and ``None`` for neutral warning.
    description : str
        Message content shown in the embed body.
    ensure_period : bool, optional
        Ensure ``description`` ends with a period for consistency.
    """
    content = description.strip()
    if ensure_period and content and not content.endswith((".", "!", "?")):
        content = f"{content}."

    if success is True:
        color = disnake.Color(int(colors.green))
    elif success is False:
        color = disnake.Color(int(colors.red))
    else:
        color = disnake.Color(int(colors.yellow))

    return disnake.Embed(description=content, color=color)


__all__ = ["status_card"]
