"""Static configuration constants for the developer tooling extension.

This module centralizes immutable identifiers used by the developer command
suite, ensuring consistent access control and command registration across
environments.

Usage
-----
These constants are imported by :mod:`spooky.bot.extensions.devtool` and its
submodules to define scope for privileged operations::

    from spooky.bot.extensions.devtool.constants import DEVELOPER_GUILD_ID, DEVELOPER_IDS

Notes
-----
- ``DEVELOPER_GUILD_ID`` restricts where developer-only commands are registered.
- ``DEVELOPER_IDS`` enumerates the Discord user IDs authorized to invoke
  privileged commands or subcommands.
"""

from __future__ import annotations

__all__ = ["DEVELOPER_GUILD_ID", "DEVELOPER_IDS"]

DEVELOPER_GUILD_ID: int = 1421826351710736640
"""The guild ID in which developer-only commands are registered and exposed."""

DEVELOPER_IDS: frozenset[int] = frozenset({404264989147529217, 150665783268212746})
"""Set of Discord user IDs authorized to execute developer-only commands."""
