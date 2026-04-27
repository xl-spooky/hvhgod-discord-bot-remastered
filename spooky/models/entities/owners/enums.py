from __future__ import annotations

from enum import Enum

__all__ = ["AuthorizationAccess"]


class AuthorizationAccess(str, Enum):
    """Configuration areas available to authorized members."""

    FAKE_PERMISSIONS = "fake_permissions"
    COMMANDS = "commands"
    MODERATION = "moderation"
    AUTO = "auto"

    @property
    def label(self) -> str:
        """Human-friendly label for display in UI controls."""
        return {
            AuthorizationAccess.FAKE_PERMISSIONS: "Fake Permissions",
            AuthorizationAccess.COMMANDS: "Commands",
            AuthorizationAccess.MODERATION: "Moderation",
            AuthorizationAccess.AUTO: "Auto",
        }[self]
