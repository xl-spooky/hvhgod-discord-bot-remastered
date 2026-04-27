"""Reusable helpers for rendering boolean toggle UI (labels, styles, emojis).

This module centralizes presentation logic for boolean ON/OFF values across the
project — particularly useful for button labels, embed text, and toggle UIs.
By keeping formatting rules here, we maintain consistent display semantics and
easily adjust styling/wording in one place if the brand tone evolves.

Included helpers:
-----------------
- :func:`label_on_off` - Generates labels like ``"Prefix ON"`` or ``"Prefix OFF"``.
- :func:`style_for_bool` - Chooses a ``disnake.ButtonStyle`` based on toggle state.
- :func:`label_and_style` - Convenience pairing of label and button style.
- :func:`emoji_for_bool` - Project-specific emoji representation of boolean values.

Example
-------
>>> label, style = label_and_style("Logging", True)
>>> print(label, style)
"Logging ON", ButtonStyle.success
"""

from __future__ import annotations

import disnake
from spooky.core import emojis

__all__ = ["emoji_for_bool", "label_and_style", "label_on_off", "style_for_bool"]


def label_on_off(prefix: str, value: bool) -> str:
    """Return a label like ``"<prefix> ON"`` or ``"<prefix> OFF"``.

    Parameters
    ----------
    prefix : str
        Text prefix describing the feature or setting ("Logging", "Mute", etc.).
    value : bool
        Boolean state to represent.

    Returns
    -------
    str
        A formatted label combining the prefix and ON/OFF based on ``value``.

    Notes
    -----
    - Capitalization and wording are standardized here to remain consistent.
    """
    return f"{prefix} {'ON' if value else 'OFF'}"


def style_for_bool(value: bool) -> disnake.ButtonStyle:
    """Map a boolean to a ``disnake.ButtonStyle``.

    Parameters
    ----------
    value : bool
        The state of the toggle.

    Returns
    -------
    disnake.ButtonStyle
        ``ButtonStyle.success`` if ``True``; ``ButtonStyle.danger`` if ``False``.
    """
    return disnake.ButtonStyle.success if value else disnake.ButtonStyle.danger


def label_and_style(prefix: str, value: bool) -> tuple[str, disnake.ButtonStyle]:
    """Return both label and ``ButtonStyle`` for a toggle in a single step.

    Parameters
    ----------
    prefix : str
        The label prefix ("Logging", "Welcome DM", etc.).
    value : bool
        True/False value determining the label suffix and style.

    Returns
    -------
    tuple[str, disnake.ButtonStyle]
        A tuple containing the ON/OFF label and its matching button style.
    """
    return label_on_off(prefix, value), style_for_bool(value)


def emoji_for_bool(value: bool) -> str:
    """Return a project-defined emoji for a boolean state.

    Parameters
    ----------
    value : bool
        The state being visualized.

    Returns
    -------
    str
        ``emojis.bool_true`` if ``True``; otherwise ``emojis.bool_false``.

    Notes
    -----
    - Emoji mappings live under ``spooky.core.emojis`` and can be updated
      centrally without changing references here.
    """
    return emojis.bool_true if value else emojis.bool_false
