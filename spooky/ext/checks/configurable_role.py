"""Reusable check helpers for role target validation."""

from __future__ import annotations

from dataclasses import dataclass

import disnake
from spooky.bot import Spooky
from spooky.models import ensure_role

__all__ = ["ConfigurableRoleCheck", "validate_configurable_role"]


@dataclass(slots=True)
class ConfigurableRoleCheck:
    """Result from validating whether a role can be configured."""

    allowed: bool
    reason: str | None
    role: disnake.Role | None

    @classmethod
    def success(cls, role: disnake.Role) -> ConfigurableRoleCheck:
        return cls(True, None, role)

    @classmethod
    def failure(cls, reason: str) -> ConfigurableRoleCheck:
        return cls(False, reason, None)


def _role_is_booster(role: disnake.Role) -> bool:
    """Return whether a role is a Nitro booster role."""
    tags = getattr(role, "tags", None)
    if tags is not None and getattr(tags, "premium_subscriber", False):
        return True

    checker = getattr(role, "is_premium_subscriber", None)
    if callable(checker):
        return bool(checker())
    if checker is not None:
        return bool(checker)
    return False


async def validate_configurable_role(
    bot: Spooky, guild_id: int, role: disnake.Role | disnake.Object
) -> ConfigurableRoleCheck:
    """Ensure ``role`` belongs to the guild and is not managed or a booster."""
    role_guild_id = getattr(getattr(role, "guild", None), "id", None)
    if (
        not isinstance(role, disnake.Role)
        or role_guild_id is None
        or int(role_guild_id) != guild_id
    ):
        ensured = await ensure_role(bot, guild_id, int(role.id))
        if ensured is None:
            return ConfigurableRoleCheck.failure("Role not found in this guild.")
        role = ensured

    if getattr(role, "managed", False):
        return ConfigurableRoleCheck.failure("Managed roles cannot be configured.")

    if _role_is_booster(role):
        return ConfigurableRoleCheck.failure("Booster roles cannot be configured.")

    return ConfigurableRoleCheck.success(role)
