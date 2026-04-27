"""Common time utilities for parsing and formatting durations."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

__all__ = [
    "format_duration_label",
    "parse_duration",
    "to_expiration",
    "utcnow",
]

_DURATION_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>[smhdw])", re.IGNORECASE)
_DURATION_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86_400,
    "w": 604_800,
}


def utcnow() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


def parse_duration(duration: str | None) -> timedelta | None:
    """Convert a shorthand duration string into a ``timedelta``.

    Examples
    --------
    ``1d12h`` → 1 day, 12 hours
    ``30m`` → 30 minutes
    """
    if duration is None:
        return None

    tokens = list(_DURATION_PATTERN.finditer(duration.strip()))
    if not tokens:
        return None

    seconds = 0
    for token in tokens:
        value = int(token.group("value"))
        unit = token.group("unit").lower()
        seconds += value * _DURATION_UNIT_SECONDS[unit]

    if seconds <= 0:
        return None

    return timedelta(seconds=seconds)


def format_duration_label(duration: timedelta) -> str:
    """Return a human-readable label for a duration."""
    total_seconds = int(duration.total_seconds())
    remaining = total_seconds
    parts: list[str] = []

    for suffix, unit_seconds in ("w", 604_800), ("d", 86_400), ("h", 3_600), ("m", 60), ("s", 1):
        if remaining < unit_seconds:
            continue
        value, remaining = divmod(remaining, unit_seconds)
        parts.append(f"{value}{suffix}")

    return " ".join(parts) if parts else "0s"


def to_expiration(
    duration: timedelta | None, *, reference: datetime | None = None
) -> datetime | None:
    """Return an expiration timestamp based on ``duration``.

    Parameters
    ----------
    duration:
        Amount of time to add to the reference. ``None`` returns ``None``.
    reference:
        Timestamp used as the baseline. Defaults to :func:`utcnow`.
    """
    if duration is None:
        return None

    base = reference or utcnow()
    return base + duration
