"""Async SQLAlchemy engine/session management for Spooky.

This module centralizes creation and lifecycle management of the project's
**async** SQLAlchemy engine and sessions. It provides:

- A lightweight :class:`DatabaseManager` holding the engine and session factory.
- ContextVar-based global registration so code can acquire the current manager.
- A safe, nestable :func:`get_session` context manager that **reuses** the
  active session when called inside an existing session scope.
- Helpers to initialize/shutdown the global manager and to create ad-hoc
  managers for testing or tooling.

Design
------
- **One engine per process**: created via :func:`init_manager` and stored in a
  ContextVar for easy access.
- **Session reuse**: nested calls to :func:`get_session` will return the same
  session object and will **not** commit/close it prematurely.
- **Transaction safety**: the outermost :func:`get_session` scope commits on
  normal exit, rolls back on exception, and always closes the session.
- **Async-first**: Uses SQLAlchemy AsyncEngine/AsyncSession throughout.

Examples
--------
Initialize once at startup:

>>> await init_manager(url="postgresql+asyncpg://user:pass@host/db")

Run a query:

>>> async with get_session() as session:
...     rows = await session.execute(...)

Nested session reuse (only the outer scope commits/closes):

>>> async with get_session() as s1:
...     async with get_session() as s2:
...         assert s1 is s2

Create an isolated manager (e.g., for tests) without registering globally:

>>> mgr = await create_manager(echo=True)
>>> async with mgr.session_factory() as session:
...     ...

Notes
-----
- :func:`get_session` is the *preferred* way to obtain a session in app code.
- Use :func:`shutdown_manager` during graceful shutdown to dispose the engine
  and clear ContextVar state.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from types import SimpleNamespace, TracebackType
from typing import Any, cast

from asyncpg import TooManyConnectionsError
from loguru import logger
from spooky.core import get_database_engine_options, get_database_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import DatabaseManager, SessionFactory, SessionState

__all__ = [
    "DatabaseManager",
    "SessionFactory",
    "SessionManager",
    "configure_manager",
    "create_manager",
    "current_manager",
    "get_session",
    "init_manager",
    "shutdown_manager",
]

# internal synchronization and context state
_manager_lock = asyncio.Lock()
_recovery_lock = asyncio.Lock()
_process_manager = SimpleNamespace(value=None)
_manager_ctx: ContextVar[DatabaseManager | None] = ContextVar("spooky_db_manager", default=None)
_session_ctx: ContextVar[SessionState | None] = ContextVar("spooky_db_session", default=None)
_last_recovery = SimpleNamespace(ts=0.0)
_RECOVERY_BACKOFF_SECONDS = 5.0
_circuit_gate = asyncio.Event()
_circuit_gate.set()
_circuit_reset_task = SimpleNamespace(task=None)


async def create_manager(
    *,
    url: str | None = None,
    echo: bool | None = None,
    reuse_process_manager: bool = True,
    **engine_overrides: Any,
) -> DatabaseManager:
    """Create a new :class:`DatabaseManager` **without** registering it globally.

    Parameters
    ----------
    url:
        Database URL. If omitted, :func:`spooky.core.get_database_url` is used.
    echo:
        If provided, overrides SQLAlchemy's engine ``echo`` setting.
    **engine_overrides:
        Additional keyword args forwarded to :func:`create_async_engine`
        (e.g., ``pool_size``, ``max_overflow``, etc.). Options from
        :func:`spooky.core.get_database_engine_options` are used as a base
        and updated with these overrides.

    Returns
    -------
    DatabaseManager
        A manager containing an AsyncEngine and a bound session factory.

    Notes
    -----
    - The returned manager is **not** installed as the global manager. Use
      :func:`configure_manager` if you want to make it current.
    - By default, if a process-wide manager already exists, it is returned to
      avoid creating multiple pools in the same service. Pass
      ``reuse_process_manager=False`` when an isolated manager is explicitly
      required (e.g., certain tests or CLIs).
    """
    cached = _process_manager.value
    if reuse_process_manager and cached is not None:
        return cached

    database_url = url or get_database_url()
    options = get_database_engine_options()
    options.update(engine_overrides)
    if echo is not None:
        options["echo"] = echo

    engine = create_async_engine(database_url, pool_pre_ping=True, **options)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    pool_size = options.get("pool_size", 5)
    max_overflow = options.get("max_overflow", 0)
    budget = max(1, pool_size + max_overflow)
    session_budget = asyncio.Semaphore(budget)
    manager = DatabaseManager(
        engine=engine,
        session_factory=factory,
        session_budget=session_budget,
    )
    _process_manager.value = manager
    return manager


async def init_manager(
    *,
    url: str | None = None,
    echo: bool | None = None,
    **engine_overrides: Any,
) -> DatabaseManager:
    """Initialize and register the **global** database manager.

    Safe under concurrency: creation is protected by an async lock and
    double-checked to avoid duplicate initialization.

    Parameters
    ----------
    url:
        Database URL override. Defaults to :func:`spooky.core.get_database_url`.
    echo:
        Optional engine echo override.
    **engine_overrides:
        Extra engine kwargs merged over
        :func:`spooky.core.get_database_engine_options`.

    Returns
    -------
    DatabaseManager
        The active (existing or newly-created) global manager.
    """
    manager = _manager_ctx.get()
    if manager is not None:
        return manager

    async with _manager_lock:
        manager = _manager_ctx.get()
        if manager is not None:
            return manager

        manager = await create_manager(
            url=url, echo=echo, reuse_process_manager=True, **engine_overrides
        )
        configure_manager(manager)
        return manager


def configure_manager(manager: DatabaseManager | None) -> None:
    """Install (or clear) the provided manager in the global ContextVar.

    Parameters
    ----------
    manager:
        The :class:`DatabaseManager` to set as current, or ``None`` to clear.
    """
    _process_manager.value = manager
    _manager_ctx.set(manager)


def current_manager() -> DatabaseManager:
    """Return the currently configured global :class:`DatabaseManager`.

    Returns
    -------
    DatabaseManager
        The active manager.

    Raises
    ------
    RuntimeError
        If the manager has not been initialized. Call :func:`init_manager`
        during application startup.
    """
    manager = _manager_ctx.get()
    if manager is None:
        raise RuntimeError("Database manager has not been initialised.")
    return manager


async def shutdown_manager() -> None:
    """Dispose of the active manager and clear ContextVar state.

    Notes
    -----
    - If no manager is installed, this is a no-op.
    - Any active session ContextVar is cleared as part of shutdown.
    """
    manager = _manager_ctx.get()
    if manager is None:
        return
    configure_manager(None)
    _session_ctx.set(None)
    await manager.dispose()


class SessionManager:
    """Async context manager wrapper around :func:`get_session`.

    This thin wrapper is useful when a context-manager *object* is preferred
    over a function-decorated context manager (e.g., composition or dependency
    injection).

    Examples
    --------
    >>> async with SessionManager() as session:
    ...     await session.execute(...)
    """

    def __init__(self) -> None:
        """Prepare an internal context for delegation."""
        self._context = get_session()
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        """Enter and return the active :class:`AsyncSession`."""
        self._session = await self._context.__aenter__()
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit, forwarding to the underlying session context manager."""
        await self._context.__aexit__(exc_type, exc, tb)
        self._session = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session with safe commit/rollback handling.

    Behavior
    --------
    - **Nested reuse**: If a session is already active in the ContextVar, it is
      yielded and **not** committed/closed by this scope.
    - **Outermost scope**: Creates a new session and on normal exit commits,
      on exception rolls back, and always closes.

    Yields
    ------
    AsyncSession
        The active SQLAlchemy async session.

    Raises
    ------
    Exception
        Any exception raised within the context triggers a rollback and is
        re-raised to the caller.

    Examples
    --------
    >>> async with get_session() as session:
    ...     await session.execute(...)
    """
    manager = _manager_ctx.get()
    if manager is None:
        manager = await init_manager()

    await _respect_circuit_breaker()

    state = _session_ctx.get()
    current_task = asyncio.current_task()

    # ContextVars copy into new asyncio tasks, so a session created in one task
    # could leak into another. Guard against cross-task reuse by treating
    # mismatched owners as a fresh session request.
    if state is None or state.owner_task is not current_task:
        await manager.session_budget.acquire()
        session = manager.session_factory()
        state = SessionState(session=session, owner_task=current_task)
        token = _session_ctx.set(state)
        outermost = True
    else:
        token = None
        outermost = False

    state.depth += 1
    try:
        yield state.session
        if outermost:
            await state.session.commit()
    except Exception as exc:
        if outermost:
            await state.session.rollback()
            await _maybe_recover_pool(manager, exc)
        raise
    finally:
        state.depth -= 1
        if outermost:
            try:
                await state.session.close()
            except Exception as close_exc:
                logger.info(
                    "Error while closing database session; releasing slot anyway",
                    error=close_exc,
                )
            if token is not None:
                _session_ctx.reset(token)
            manager.session_budget.release()


async def _respect_circuit_breaker() -> None:
    """Delay session acquisition when the pool recently saturated."""
    if _circuit_gate.is_set():
        return

    remaining = max(0.0, _circuit_reset_eta() - asyncio.get_running_loop().time())
    logger.info(
        "Database circuit open; delaying session acquisition for {delay:.2f}s",
        delay=remaining,
    )
    await _circuit_gate.wait()


async def _maybe_recover_pool(manager: DatabaseManager, exc: Exception) -> None:
    """Handle pool exhaustion errors by disposing the engine for a clean retry.

    A saturated Postgres server can start rejecting new connections with
    ``TooManyConnectionsError``. When this happens, disposing the process-wide
    engine helps release idle connections and allows the next request to build
    a fresh pool once capacity is available.
    """
    root_exc = exc
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        root_exc = exc.orig  # type: ignore[assignment]

    if isinstance(root_exc, TooManyConnectionsError):
        async with _recovery_lock:
            loop_time = asyncio.get_running_loop().time()
            if loop_time - _last_recovery.ts < _RECOVERY_BACKOFF_SECONDS:
                logger.info(
                    "skipping engine recycle; last recovery happened recently ({elapsed:.2f}s)",
                    elapsed=loop_time - _last_recovery.ts,
                )
                return

            _last_recovery.ts = loop_time
            await _open_circuit(backoff=_RECOVERY_BACKOFF_SECONDS)
            logger.info(
                "Too many Postgres connections; recycling database engine (pool={pool})",
                pool=_format_pool_status(manager),
            )
            configure_manager(None)
            _session_ctx.set(None)
            await manager.dispose()


async def _open_circuit(*, backoff: float) -> None:
    """Trip the circuit and schedule its automatic reset."""
    if _circuit_reset_task.task is not None and not _circuit_reset_task.task.done():
        _circuit_reset_task.task.cancel()
        _circuit_reset_task.task.add_done_callback(_suppress_cancelled)

    _circuit_gate.clear()
    loop = asyncio.get_running_loop()
    eta = loop.time() + backoff
    task = loop.create_task(_close_circuit_after(eta))
    task._spooky_eta = eta  # type: ignore[attr-defined]
    _circuit_reset_task.task = task


async def _close_circuit_after(eta: float) -> None:
    delay = max(0.0, eta - asyncio.get_running_loop().time())
    try:
        if delay:
            await asyncio.sleep(delay)
        _circuit_gate.set()
    finally:
        if _circuit_reset_task.task is asyncio.current_task():
            _circuit_reset_task.task = None


def _circuit_reset_eta() -> float:
    task = _circuit_reset_task.task
    if task is None:
        return 0.0
    return getattr(task, "_spooky_eta", 0.0)


def _suppress_cancelled(task: asyncio.Task[Any]) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        return


def _format_pool_status(manager: DatabaseManager) -> str:
    pool = cast(Any, manager.engine.sync_engine.pool)
    try:
        size = pool.size()
        checked_in = pool.checkedin()
        overflow = pool.overflow()
    except Exception:
        return "unknown"

    return f"size={size}, checked_in={checked_in}, overflow={overflow}"
