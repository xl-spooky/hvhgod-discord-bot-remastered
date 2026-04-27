from __future__ import annotations

from enum import StrEnum

__all__ = ["ModerationActionType"]


class ModerationActionType(StrEnum):
    """Supported moderation actions persisted by the bot."""

    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    SOFTBAN = "softban"
    HARDBAN = "hardban"
    TIMEOUT = "timeout"
    UNTIMEOUT = "untimeout"
    ADD_ROLE = "add_role"
    REMOVE_ROLE = "remove_role"
