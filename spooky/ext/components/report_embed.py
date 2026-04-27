"""Deprecated alias for :mod:`spooky.ext.components.v2.card`.

This module exists solely to maintain backward compatibility for older codebases
still using ``report_embed`` or importing palettes from the legacy namespace.

Prefer importing directly from ``spooky.ext.components.v2.card`` going forward:

>>> from spooky.ext.components.v2.card import status_card, CardPalette

Deprecation Notice
------------------
The :func:`report_embed` wrapper is considered deprecated and may be removed in a
future major version once downstream consumers migrate to :func:`status_card`.

Exports
-------
- :class:`CardPalette`
- :func:`status_card`
- :func:`report_embed` (deprecated thin wrapper)
"""

from __future__ import annotations

from disnake import Embed, ui
from spooky.ext.components.v2.card import CardPalette, status_card, status_container

__all__ = ["CardPalette", "report_container", "report_embed", "status_card", "status_container"]


def report_embed(success: bool | None, description: str, *, ensure_period: bool = True) -> Embed:
    """Backward compatible wrapper around :func:`status_card`.

    Parameters
    ----------
    success :
        Outcome indicator passed through to :func:`status_card`. ``True`` for
        success, ``False`` for error, ``None`` for warning/neutral.
    description :
        Embed body text forwarded to :func:`status_card`.
    ensure_period :
        Whether to append a trailing period if the description ends with an
        alphanumeric character.

    Returns
    -------
    disnake.Embed
        The constructed embed from :func:`status_card`.

    Notes
    -----
    This function is deprecated and retained only for compatibility with older
    code. Prefer calling :func:`status_card` directly.
    """
    return status_card(success, description, ensure_period=ensure_period)


def report_container(
    success: bool | None,
    description: str,
    *,
    ensure_period: bool = True,
) -> ui.Container:
    """Wrap for producing a status container using legacy semantics.

    This is a V2 UI-friendly equivalent of :func:`report_embed`, reusing
    :func:`status_container` to preserve expected styling and behavior while
    returning a :class:`ui.Container` instead of an embed.

    Parameters
    ----------
    success:
        Outcome indicator for the report state (see :func:`status_container`).
    description:
        Textual description of the report outcome.
    ensure_period:
        Whether to enforce sentence punctuation consistency. Defaults to
        ``True``.

    Returns
    -------
    ui.Container
        A lightweight container representing the report outcome.
    """
    return status_container(success, description, ensure_period=ensure_period)
