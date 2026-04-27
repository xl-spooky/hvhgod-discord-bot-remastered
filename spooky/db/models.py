"""Dataclasses used by the database session infrastructure."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

__all__ = [
    "DatabaseManager",
    "SessionFactory",
    "SessionState",
]

# public type alias for consumers
SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(slots=True)
class DatabaseManager:
    """Hold engine and session factory for SQLAlchemy operations."""

    engine: AsyncEngine
    session_factory: SessionFactory
    session_budget: asyncio.Semaphore

    async def dispose(self) -> None:
        """Dispose the engine and release pooled connections."""
        await self.engine.dispose()


@dataclass(slots=True)
class SessionState:
    session: AsyncSession
    depth: int = 0
    owner_task: asyncio.Task[Any] | None = None
