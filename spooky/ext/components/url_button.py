from __future__ import annotations

from disnake import ButtonStyle, ui


def url_button(label: str, url: str) -> ui.Button[None]:
    """Create a URL button without decorative emoji."""
    return ui.Button(label=label, url=url, style=ButtonStyle.gray)
