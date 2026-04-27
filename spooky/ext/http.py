"""Thin async HTTP client with optional auth and tiny TTL caches.

This module provides :class:`HttpClient`, a small wrapper around ``aiohttp`` that
centralizes a couple of convenience behaviors:

- **Shared sessions** (regular and Basic-Auth) via
  :meth:`HttpClient.create_session` / :meth:`HttpClient.create_auth_session`.
- **Simple fetch utilities**:
  - :meth:`HttpClient.get_content` — fetch raw bytes,
  - :meth:`HttpClient.get_json` — fetch JSON with a tiny in-memory TTL cache,
  - :meth:`HttpClient.resolve_redirect` — resolve the final URL (also cached).
- **(Optional) DB access plumbing** — tiny shims to the project's async SQLAlchemy
  session lifecycle, useful for jobs that need both HTTP and DB.

Design
------
- Caches are **process-local**, in-memory dicts with a **short TTL** (default 60s)
  and a **hard entry cap** (default 256). When the cap is reached, the cache is
  cleared to avoid unbounded growth (simple + predictable).
- Cache keys for JSON include the URL and a **normalized header tuple**, so
  requests that differ only by header values use distinct entries.
- This class stores shared sessions as **class-level** attributes. You are
  responsible for creating them once (e.g., at startup) and closing them on
  shutdown.

Examples
--------
Initialize sessions at startup:

>>> HttpClient.create_session(timeout=15)
>>> HttpClient.create_auth_session("user", "pass")

Use the helpers:

>>> data = await HttpClient.get_json("https://api.example.com/items")
>>> content = await HttpClient.get_content("https://cdn.example.com/file.bin")
>>> final = await HttpClient.resolve_redirect("https://t.co/xyz")

DB helpers (optional):

>>> await HttpClient.init_database(url="postgresql+asyncpg://...")  # once
>>> async with HttpClient.db_session() as session:
...     await session.execute(...)  # do DB work

Notes
-----
- Method parameters named ``header`` accept a **dict of HTTP headers** and may
  be ``None``. (We keep the name for backward compatibility.)
- This module does **not** auto-close the created ``aiohttp.ClientSession`` objects;
  ensure you close them during graceful shutdown in your app lifecycle.
"""

from __future__ import annotations

import time
from collections import abc
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import aiohttp
from spooky.db.session import (
    DatabaseManager,
    current_manager,
    get_session,
    init_manager,
    shutdown_manager,
)
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "HttpClient",
]


class HttpClient:
    """Perform HTTP requests with optional auth and simple TTL caching.

    Provides helpers to create regular and authenticated sessions, fetch raw
    content or JSON, and resolve redirects. Caches a small number of recent
    JSON and redirect results to reduce network calls.

    Class Attributes
    ----------------
    session : aiohttp.ClientSession
        Shared non-authenticated HTTP client session (set by :meth:`create_session`).
    auth_session : aiohttp.ClientSession
        Shared Basic-Auth HTTP client session (set by :meth:`create_auth_session`).
    _json_cache : dict[tuple[str, tuple[tuple[str, str], ...] | None], tuple[float, Mapping[str, Any]]]
        Tiny TTL cache for GET JSON responses. Keys are (URL, normalized-headers).
        Values are (inserted_at_epoch_seconds, parsed_json_mapping).
    _redirect_cache : dict[str, tuple[float, str]]
        Tiny TTL cache mapping an input URL to its resolved final URL.
    _cache_ttl_seconds : int
        TTL (seconds) for cached JSON/redirect entries. Defaults to 60.
    _cache_max_entries : int
        Maximum number of entries per cache before a full clear. Defaults to 256.
    _db_manager : DatabaseManager | None
        Optional reference to the global DB manager (convenience for tasks that
        combine HTTP + DB work).

    Notes
    -----
    - Caches are **best-effort**: if capacity is exceeded, the cache is cleared.
    - For scenarios requiring richer caching (LRU, persistence, invalidation),
      prefer the project's dedicated cache utilities.
    """  # noqa: E501

    __slots__ = ()

    # Shared sessions (set by create_session/create_auth_session)
    session: ClassVar[aiohttp.ClientSession]
    auth_session: ClassVar[aiohttp.ClientSession]

    # Simple in-memory TTL caches for JSON/redirect GETs
    _json_cache: ClassVar[
        dict[tuple[str, tuple[tuple[str, str], ...] | None], tuple[float, abc.Mapping[str, Any]]]
    ] = {}
    _redirect_cache: ClassVar[dict[str, tuple[float, str]]] = {}

    # Cache policy
    _cache_ttl_seconds: ClassVar[int] = 60
    _cache_max_entries: ClassVar[int] = 256

    # Optional DB manager handle
    _db_manager: ClassVar[DatabaseManager | None] = None

    # ---------------------------------------------------------------------
    # Optional DB lifecycle helpers
    # ---------------------------------------------------------------------

    @classmethod
    async def init_database(cls, **overrides: Any) -> DatabaseManager:
        """Initialise the shared database manager via SQLAlchemy.

        Parameters
        ----------
        **overrides : Any
            Keyword arguments forwarded to :func:`spooky.db.session.init_manager`
            (e.g., ``url=...``, ``echo=True``, or engine kwargs).

        Returns
        -------
        DatabaseManager
            The active (existing or newly-created) global DB manager.
        """
        manager = await init_manager(**overrides)
        cls._db_manager = manager
        return manager

    @classmethod
    async def shutdown_database(cls) -> None:
        """Shutdown the shared database manager and clear our handle.

        Notes
        -----
        - This calls :func:`spooky.db.session.shutdown_manager`.
        - Does **not** close any HTTP sessions; manage those separately.
        """
        await shutdown_manager()
        cls._db_manager = None

    @classmethod
    def get_database_manager(cls) -> DatabaseManager:
        """Return the active database manager or raise if uninitialised.

        Returns
        -------
        DatabaseManager
            The current global manager, either cached by this class or
            resolved via :func:`spooky.db.session.current_manager`.

        Raises
        ------
        RuntimeError
            If the manager has not been initialized.
        """
        if cls._db_manager is not None:
            return cls._db_manager
        return current_manager()

    @classmethod
    @asynccontextmanager
    async def db_session(cls) -> AsyncIterator[AsyncSession]:
        """Context manager yielding an async SQLAlchemy session.

        Yields
        ------
        AsyncSession
            The active session from :func:`spooky.db.session.get_session`.

        Notes
        -----
        - Supports nested reuse semantics per project session manager.
        """
        async with get_session() as session:
            yield session

    # ---------------------------------------------------------------------
    # HTTP session factories
    # ---------------------------------------------------------------------

    @classmethod
    def create_session(cls, timeout: int = 10) -> aiohttp.ClientSession:
        """Create and assign a new ``aiohttp.ClientSession``.

        Parameters
        ----------
        timeout : int, default 10
            Total request timeout (seconds) for the session.

        Returns
        -------
        aiohttp.ClientSession
            The created client session (also stored on the class as ``session``).

        Notes
        -----
        - Remember to **close** this session on shutdown: ``await session.close()``.
        """
        timeout_config = aiohttp.ClientTimeout(total=timeout)
        session = aiohttp.ClientSession(timeout=timeout_config)
        cls.session = session
        return session

    @classmethod
    def create_auth_session(cls, login: str, password: str) -> aiohttp.ClientSession:
        """Create and assign a new authenticated session using Basic Auth.

        Parameters
        ----------
        login : str
            Username for Basic authentication.
        password : str
            Password for Basic authentication.

        Returns
        -------
        aiohttp.ClientSession
            The created authenticated client session (also stored on the class
            as ``auth_session``).

        Notes
        -----
        - Remember to **close** this session on shutdown.
        """
        session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(login, password))
        cls.auth_session = session
        return session

    # ---------------------------------------------------------------------
    # Fetch utilities
    # ---------------------------------------------------------------------

    @classmethod
    async def get_content(cls, url: str, /, header: dict[str, str] | None = None) -> bytes:
        """Fetch raw bytes from a URL.

        Parameters
        ----------
        url : str
            The URL to retrieve content from.
        header : dict[str, str] | None, optional
            Optional HTTP headers to include in the request.

        Returns
        -------
        bytes
            The response body as raw bytes.

        Raises
        ------
        aiohttp.ClientResponseError
            For non-2xx responses after :meth:`raise_for_status`.
        aiohttp.ClientError
            For network/connection-level errors.
        """
        async with cls.session.get(url, headers=header) as response:
            response.raise_for_status()
            return await response.content.read()

    @classmethod
    async def get_json(
        cls,
        url: str,
        /,
        header: dict[str, str] | None = None,
        *,
        use_cache: bool = True,
    ) -> abc.Mapping[str, Any]:
        """Fetch and return JSON from a URL (with a tiny TTL cache).

        Parameters
        ----------
        url : str
            The URL to retrieve JSON from.
        header : dict[str, str] | None, optional
            Optional HTTP headers for the request.
        use_cache : bool, default True
            If ``True``, consult and populate the in-memory TTL cache.

        Returns
        -------
        Mapping[str, Any]
            The parsed JSON data.

        Raises
        ------
        aiohttp.ClientResponseError
            For non-2xx responses after :meth:`raise_for_status`.
        aiohttp.ClientError
            For network/connection-level errors.
        ValueError
            If response body cannot be parsed as JSON.
        """
        cache_key = (url, tuple(sorted(header.items())) if header else None)
        now = time.time()

        if use_cache:
            cached = cls._json_cache.get(cache_key)
            if cached and (now - cached[0]) <= cls._cache_ttl_seconds:
                return cached[1]

        async with cls.session.get(url, headers=header) as response:
            response.raise_for_status()
            data = await response.json()

        if use_cache:
            # Enforce max size to avoid unbounded growth.
            if len(cls._json_cache) >= cls._cache_max_entries:
                cls._json_cache.clear()
            cls._json_cache[cache_key] = (now, data)

        return data

    @classmethod
    async def resolve_redirect(cls, url: str, *, use_cache: bool = True) -> str:
        """Resolve and return the final URL after following redirects.

        Parameters
        ----------
        url : str
            The initial URL to resolve.
        use_cache : bool, default True
            If ``True``, consult and populate the in-memory TTL cache.

        Returns
        -------
        str
            The final URL after redirection.

        Raises
        ------
        aiohttp.ClientResponseError
            For non-2xx responses after :meth:`raise_for_status`.
        aiohttp.ClientError
            For network/connection-level errors.
        """
        now = time.time()

        if use_cache:
            cached = cls._redirect_cache.get(url)
            if cached and (now - cached[0]) <= cls._cache_ttl_seconds:
                return cached[1]

        async with cls.session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            final_url = str(response.url)

        if use_cache:
            if len(cls._redirect_cache) >= cls._cache_max_entries:
                cls._redirect_cache.clear()
            cls._redirect_cache[url] = (now, final_url)

        return final_url
