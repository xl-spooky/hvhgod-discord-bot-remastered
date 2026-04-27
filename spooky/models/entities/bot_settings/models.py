"""Command gating models: guild-wide disables and granular role/user overrides.

This module defines three small ORM tables used by Spooky's **command
permission system**:

- :class:`GuildCommandDisabled` — guild-level switch to disable a command
  globally within a server.
- :class:`GuildCommandRoleOverride` — per-role allow/deny for a command.
- :class:`GuildCommandUserOverride` — per-user allow/deny for a command.

Design & Precedence
-------------------
A typical, deterministic evaluation order used by our resolvers is:

1. **User override** (highest priority)
2. **Role overrides** (e.g., "any allow wins" or "deny wins" — policy-defined)
3. **Guild disabled** (base/default if no higher-priority rule applies)

All three models enforce **uniqueness** over their identifying tuple to prevent
duplicate rules and keep resolution logic O(1) per key.

Notes
-----
- These tables do not impose a merge policy; the **resolver** (application
  code) defines how conflicting role overrides are combined.
- Consider emitting moderation/audit logs when overrides change.
- String column ``command`` should be a canonical command identifier
  (e.g., ``"tickets.open"`` or a normalized slash-command path).

Examples
--------
Disable a command guild-wide:

>>> GuildCommandDisabled(guild_id=123, command="tickets.open")

Allow a command for a specific role:

>>> GuildCommandRoleOverride(
...     guild_id=123, role_id=456, command="tickets.open", allowed=True
... )

Explicitly deny a command for a specific user:

>>> GuildCommandUserOverride(
...     guild_id=123, user_id=789, command="tickets.open", allowed=False
... )
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = [
    "GuildCommandDisabled",
    "GuildCommandRoleOverride",
    "GuildCommandUserOverride",
]


class GuildCommandDisabled(Base):
    """Guild-level command disable list.

    Purpose
    -------
    Records commands that are **globally disabled** within a specific guild.
    Resolution layers (role/user overrides) can still selectively re-allow
    behavior depending on your enforcement strategy.

    Attributes
    ----------
    id:
        Surrogate primary key.
    guild_id:
        Discord guild snowflake. Indexed for fast lookups.
    command:
        Canonical command identifier (e.g., ``"tickets.open"``). Indexed.

    Constraints
    -----------
    - ``UNIQUE (guild_id, command)`` ensures a single disable row per command
      within a guild.

    Notes
    -----
    - Downstream resolvers should define a clear precedence order between this
      table and per-role/per-user overrides. A common policy is:
      **User override > Role override > Guild disabled**.
    """

    __tablename__ = "guild_command_disabled"
    __table_args__ = (UniqueConstraint("guild_id", "command"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(128), index=True)


class GuildCommandRoleOverride(Base):
    """Per-role command allow/deny override within a guild.

    Purpose
    -------
    Provides a **role-scoped** switch to allow or deny an individual command
    for members holding the role.

    Attributes
    ----------
    id:
        Surrogate primary key.
    guild_id:
        Discord guild snowflake. Indexed.
    role_id:
        Discord role snowflake. Indexed.
    command:
        Canonical command identifier. Indexed.
    allowed:
        ``True`` explicitly allows, ``False`` explicitly denies for this role.

    Constraints
    -----------
    - ``UNIQUE (guild_id, role_id, command)`` prevents duplicate entries.

    Notes
    -----
    - If members have multiple roles with conflicting overrides, your resolver
      should define a deterministic merge strategy (e.g., **any allow wins**,
      or **deny wins**).
    - Typical precedence: **User override > Role override > Guild disabled**.
    """

    __tablename__ = "guild_command_role_override"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", "command"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(128), index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class GuildCommandUserOverride(Base):
    """Per-user command allow/deny override within a guild.

    Purpose
    -------
    Provides a **user-scoped** switch to allow or deny an individual command
    for a specific member in a guild, typically taking highest precedence.

    Attributes
    ----------
    id:
        Surrogate primary key.
    guild_id:
        Discord guild snowflake. Indexed.
    user_id:
        Discord user snowflake. Indexed.
    command:
        Canonical command identifier. Indexed.
    allowed:
        ``True`` explicitly allows, ``False`` explicitly denies for this user.

    Constraints
    -----------
    - ``UNIQUE (guild_id, user_id, command)`` prevents duplicate entries.

    Notes
    -----
    - Typical precedence: **User override > Role override > Guild disabled**.
    - Consider adding auditing around changes to user overrides for moderation
      transparency.
    """

    __tablename__ = "guild_command_user_override"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "command"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    command: Mapped[str] = mapped_column(String(128), index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
