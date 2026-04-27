"""Minimal embed card helpers used by context/telemetry."""

from __future__ import annotations

import disnake


def status_card(success: bool, description: str) -> disnake.Embed:
    """Return a simple success/error embed card."""
    color = disnake.Color.green() if success else disnake.Color.red()
    return disnake.Embed(description=description, color=color)


__all__ = ["status_card"]
