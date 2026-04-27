"""Public re-export surface for the async Redis manager.

This module provides a simplified import path for Redis-related functionality
by re-exporting the key interfaces from :mod:`.session`. Projects can
import directly from ``spooky.redis`` rather than drilling into
implementation modules.

Re-exported components include:
- :class:`RedisManager`: container for the async Redis client.
- :func:`create_manager`: construct an unregistered manager instance.
- :func:`configure_manager`: install or clear the global manager.
- :func:`init_manager`: initialize and register the global manager (idempotent).
- :func:`current_manager`: retrieve the active registered manager.
- :func:`get_client`: retrieve the underlying Redis client.
- :func:`shutdown_manager`: close and unregister the manager.

Example
-------
>>> from spooky.redis import init_manager, get_client
>>> await init_manager()
>>> redis = get_client()
>>> await redis.set("key", "value")
"""

from __future__ import annotations

from .session import (
    RedisManager,
    configure_manager,
    create_manager,
    current_manager,
    get_client,
    init_manager,
    shutdown_manager,
)

__all__ = [
    "RedisManager",
    "configure_manager",
    "create_manager",
    "current_manager",
    "get_client",
    "init_manager",
    "shutdown_manager",
]
