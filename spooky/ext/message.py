"""Message templates for private runtime workflows."""

from __future__ import annotations

BUYER_WELCOME_TEMPLATE = (
    "Welcome {user}🎉\n"
    "\n"
    "This is your private buyer space — glad to have you here.\n"
    "Please check {vac_tips_channel} for vac tips and safety using these configs.\n"
    "Your config information will be posted in the CONFIG CODES forum thread.\n"
    "For direct support, open the CONTACT US thread and chat with us there."
)

CONFIG_CODE_TEMPLATE = (
    "## 🔐 {bundle} • {branch}\n"
    "- **Color:** {color}\n"
    "- **Version:** `{version}`\n"
    "- **Code:** ||{code}||"
)

BOOSTING_SERVICES_TEMPLATE = (
    "# BOOSTING SERVICES\n\n"
    "We offer fast and reliable boosting services with safe procedures.\n\n"
    "## PRICING\n"
    "- Standard Boost Game: 1€\n"
    "- Yellow Trust Boost (Perma Yellow): 1.5€ / game\n"
    "- Red Trust Boost: 2€ / game\n\n"
    "## HOW IT WORKS\n"
    "We do NOT require your account credentials.\n\n"
    "Login is done securely via Steam QR Code only.\n\n"
    "## NOTES\n"
    "- Prices are per game\n"
    "- Make sure to specify your current trust factor before starting\n"
    "- Fast handling & consistent service\n\n"
    "Open a ticket to get started."
)


def render_buyer_welcome(*, user_mention: str, vac_tips_channel_mention: str) -> str:
    """Return the buyer welcome message with runtime placeholders resolved."""
    return BUYER_WELCOME_TEMPLATE.format(
        user=user_mention,
        vac_tips_channel=vac_tips_channel_mention,
    )


def render_config_code_update(
    *,
    bundle: str,
    branch: str,
    color: str,
    code: str,
    version: str,
) -> str:
    """Return a formatted config code payload for buyer config threads."""
    return CONFIG_CODE_TEMPLATE.format(
        bundle=bundle,
        branch=branch,
        color=color,
        code=code,
        version=version,
    )


def render_boosting_services_message() -> str:
    """Return the standard BOOSTING SERVICES thread payload."""
    return BOOSTING_SERVICES_TEMPLATE


__all__ = [
    "BOOSTING_SERVICES_TEMPLATE",
    "BUYER_WELCOME_TEMPLATE",
    "CONFIG_CODE_TEMPLATE",
    "render_boosting_services_message",
    "render_buyer_welcome",
    "render_config_code_update",
]
