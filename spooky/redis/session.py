"""Async Redis client manager for Spooky.

This module mirrors the design of :mod:`spooky.db.session` but for Redis,
providing a thin manager that centralizes creation, access, and cleanup of
the shared :class:`redis.asyncio.Redis` client used across the project.

Features
--------
- ``RedisManager`` dataclass that holds the async Redis client.
- ContextVar-backed registration so code can fetch the current manager via
  :func:`current_manager` and the underlying client via :func:`get_client`.
- ``init_manager`` / ``shutdown_manager`` helpers for lifecycle management.
- ``create_manager`` for ad-hoc managers (e.g., testing) without touching
  global state.

Typical usage
-------------
Initialize once during startup::

    >>> from spooky.redis import init_manager
    >>> await init_manager()

Obtain a client inside your feature code::

    >>> from spooky.redis import get_client
    >>> redis = get_client()
    >>> await redis.set("example", "value", ex=60)

Shutdown gracefully::

    >>> from spooky.redis import shutdown_manager
    >>> await shutdown_manager()
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from loguru import logger
from spooky.core import get_redis_options, get_redis_url

from redis.asyncio import Redis
from redis.exceptions import RedisError

__all__ = [
    "RedisManager",
    "configure_manager",
    "create_manager",
    "current_manager",
    "get_client",
    "init_manager",
    "shutdown_manager",
]


@dataclass(slots=True)
class RedisManager:
    """Container for the async Redis client.

    Attributes
    ----------
    client
        The active :class:`redis.asyncio.Redis` client instance.
    """

    client: Redis

    async def close(self) -> None:
        """Close the underlying Redis client and release resources.

        Notes
        -----
        - Handles compatibility between ``aclose()`` (newer clients) and
          ``close()`` (older versions).
        - Attempts to disconnect the connection pool if exposed by the client.
        - Any :class:`RedisError` raised during shutdown is logged at DEBUG
          level and suppressed to avoid noisy teardown.
        """
        try:
            await self.client.aclose()
        except AttributeError:  # pragma: no cover - compatibility guard
            await self.client.close()
        except RedisError as exc:  # pragma: no cover - defensive logging
            logger.debug("Ignoring Redis close error: {}", exc)
        try:
            disconnect = self.client.connection_pool.disconnect  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover - compatibility guard
            return
        try:
            result = disconnect()
            if asyncio.iscoroutine(result):
                await result
        except RedisError as exc:  # pragma: no cover - defensive logging
            logger.debug("Ignoring Redis pool disconnect error: {}", exc)


_manager_lock = asyncio.Lock()
_manager_ctx: ContextVar[RedisManager | None] = ContextVar("spooky_redis_manager", default=None)


async def create_manager(*, url: str | None = None, **overrides: Any) -> RedisManager:
    """Create a new :class:`RedisManager` **without** registering it globally.

    Parameters
    ----------
    url
        Redis connection URL. Defaults to :func:`spooky.core.get_redis_url`
        when omitted.
    **overrides
        Keyword arguments forwarded to :meth:`redis.asyncio.Redis.from_url`.

    Returns
    -------
    RedisManager
        The constructed manager containing the async Redis client.

    Notes
    -----
    - ``overrides`` is merged on top of defaults from :func:`get_redis_options`.
    - Use :func:`configure_manager` to install the returned manager globally.
    """
    redis_url = url or get_redis_url()
    options = get_redis_options()
    options.update(overrides)

    client = Redis.from_url(redis_url, **options)
    return RedisManager(client=client)


async def init_manager(*, url: str | None = None, **overrides: Any) -> RedisManager:
    """Initialize and globally register the Redis manager (idempotent).

    If a manager is already installed, it is returned unchanged.

    Parameters
    ----------
    url
        Explicit Redis URL override. When omitted, derived from environment.
    **overrides
        Keyword arguments forwarded to :func:`create_manager`.

    Returns
    -------
    RedisManager
        The active (existing or newly created) manager.

    Thread Safety
    -------------
    Global installation is guarded by an ``asyncio.Lock`` to prevent races
    during concurrent startup paths.
    """
    async with _manager_lock:
        existing = _manager_ctx.get()
        if existing is not None:
            return existing

        manager = await create_manager(url=url, **overrides)
        configure_manager(manager)
        return manager


def configure_manager(manager: RedisManager | None) -> None:
    """Install (or clear) the provided manager in the global ContextVar.

    Parameters
    ----------
    manager
        The manager to install. Pass ``None`` to clear the current manager.
    """
    _manager_ctx.set(manager)


def current_manager() -> RedisManager:
    """Return the currently configured global :class:`RedisManager`.

    Returns
    -------
    RedisManager
        The active manager.

    Raises
    ------
    RuntimeError
        If the manager has not been initialized via :func:`init_manager`.
    """
    manager = _manager_ctx.get()
    if manager is None:
        raise RuntimeError("Redis manager has not been initialised.")
    return manager


def get_client() -> Redis:
    """Return the active async Redis client.

    Returns
    -------
    redis.asyncio.Redis
        The client from :func:`current_manager`.

    Raises
    ------
    RuntimeError
        If no manager has been initialized.
    """
    return current_manager().client


async def shutdown_manager() -> None:
    """Close the active Redis manager and clear ContextVar state.

    Notes
    -----
    - If no manager is installed, this is a no-op.
    - Errors during shutdown are logged at DEBUG level inside
      :meth:`RedisManager.close` and are suppressed.
    """
    manager = _manager_ctx.get()
    if manager is None:
        return

    configure_manager(None)
    await manager.close()
