"""Lightweight check helpers for bot extensions."""

from .authorization import AuthorizationAccess, is_owner_or_authorized_for_access
from .configurable_member import ConfigurableMemberCheck, validate_configurable_member
from .configurable_role import ConfigurableRoleCheck, validate_configurable_role
from .owner import is_guild_owner

__all__ = [
    "AuthorizationAccess",
    "ConfigurableMemberCheck",
    "ConfigurableRoleCheck",
    "is_guild_owner",
    "is_owner_or_authorized_for_access",
    "validate_configurable_member",
    "validate_configurable_role",
]
