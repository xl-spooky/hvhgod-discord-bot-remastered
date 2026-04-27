"""Async SQLAlchemy engine and session management for Spooky.

This module exposes the key primitives used for interacting with Spooky's
asynchronous SQLAlchemy infrastructure. It acts as the public-facing access
layer for creating, configuring, and retrieving the database engine and
sessions.

Key Components
--------------
- :class:`DatabaseManager` - Holds the async engine and session factory.
- :class:`SessionManager` - Async context manager wrapper around ``get_session``.
- :func:`create_manager` - Create a new manager instance (not globally registered).
- :func:`init_manager` - Initialize and globally register the database manager.
- :func:`configure_manager` - Manually set or clear the active manager.
- :func:`current_manager` - Retrieve the active manager or raise an error if missing.
- :func:`shutdown_manager` - Dispose and clear the global manager.
- :func:`get_session` - Async context manager that yields a managed session tied to commit/rollback rules.

Typical Usage
-------------
Initialize the database on bot startup:

>>> from spooky.db import init_manager
>>> await init_manager(url="postgresql+asyncpg://...")

Use a session inside an async function:

>>> from spooky.db import get_session
>>> async with get_session() as session:
...     await session.execute(...)

Or wrap with :class:`SessionManager`:

>>> from spooky.db import SessionManager
>>> async with SessionManager() as session:
...     result = await session.execute(...)

Notes
-----
- Sessions obtained from :func:`get_session` commit automatically unless an exception occurs.
- Nested calls to :func:`get_session` reuse the active session where appropriate.
- :func:`shutdown_manager` should be called during application shutdown to ensure proper cleanup.
"""  # noqa: E501

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .session import (
    DatabaseManager,
    SessionManager,
    configure_manager,
    create_manager,
    current_manager,
    get_session,
    init_manager,
    shutdown_manager,
)

__all__ = [
    "AsyncSession",
    "DatabaseManager",
    "SessionManager",
    "configure_manager",
    "create_manager",
    "current_manager",
    "get_session",
    "init_manager",
    "shutdown_manager",
]
