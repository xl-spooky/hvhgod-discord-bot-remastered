"""Lightweight string utility helpers.

This module groups small string manipulation helpers used across the project.
It is intentionally minimal and dependency-free, providing simple and safe
operations that are frequently needed in embeds, logs, or UI previews.

Currently included:
- :func:`truncate` - Restricts string length and appends an ellipsis if exceeded.

Notes
-----
- These helpers are designed for performance and simplicity, not linguistic parsing.
- Additional utilities (e.g., safe markdown escaping or slugification) may be added
  here in the future.
"""

from __future__ import annotations


def truncate(s: str, n: int) -> str:
    """Trim a string to at most ``n`` characters, appending an ellipsis if truncated.

    Parameters
    ----------
    s : str
        Input string. ``None`` or falsy values are treated as empty.
    n : int
        Maximum allowed output length before truncation occurs.

    Returns
    -------
    str
        The unmodified string if its length is less than or equal to ``n``.
        Otherwise, a truncated string consisting of the first ``n`` characters
        with ``"..."`` appended.

    Notes
    -----
    - This function does a simple character-based cut and does not attempt to
      preserve full words.
    - Trimming includes leading/trailing whitespace removal before processing.
    """
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "..."
