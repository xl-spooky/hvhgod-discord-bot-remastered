"""Feature-specific helper namespace for database sync hooks.

This module acts as a namespace aggregator for feature-scoped cleanup
and synchronization helpers used by the DB sync pipeline. Each feature
(e.g., snipe, economy, notifications) can expose its own utility module
that defines high-level operations (such as pruning, deletion, or
pre-synchronization checks).

Currently exposed features:
- ``snipe``: maintenance helpers for snipe-related database models
  (expired entry cleanup, per-guild pruning, etc.).

The public API of this package is intentionally narrow. Import specific
helpers directly from submodules when writing new sync logic.

Example
-------
>>> from spooky.bot.extensions.hooks.db_sync.features import snipe
>>> summary = await snipe.delete_expired_entries(bot)
>>> summary.messages_deleted
"""

from __future__ import annotations

from . import auto, command_gate, logging, moderation, owners, permissions, premium, snipe

__all__ = [
    "auto",
    "command_gate",
    "logging",
    "moderation",
    "owners",
    "permissions",
    "premium",
    "snipe",
]
