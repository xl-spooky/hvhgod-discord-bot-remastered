"""Message templates for private runtime workflows."""

from __future__ import annotations

BUYER_WELCOME_TEMPLATE = (
    "Welcome {user}🎉\n"
    "\n"
    "This is your private buyer space — glad to have you here.\n"
    "Please check {vac_tips_channel} for vac tips and safety using these configs.\n"
    "Your config information will be posted in the CONFIG CODES forum thread."
)


def render_buyer_welcome(*, user_mention: str, vac_tips_channel_mention: str) -> str:
    """Return the buyer welcome message with runtime placeholders resolved."""
    return BUYER_WELCOME_TEMPLATE.format(
        user=user_mention,
        vac_tips_channel=vac_tips_channel_mention,
    )


__all__ = ["BUYER_WELCOME_TEMPLATE", "render_buyer_welcome"]
