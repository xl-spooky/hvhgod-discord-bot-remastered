"""Advanced TTL caching helpers for resolving Discord entities.

This module provides small, fast **time-to-live (TTL)** caches and ergonomic
helpers to resolve common Discord entities using ``disnake`` with REST
fallbacks, while also ensuring corresponding DB rows exist where appropriate.

Features
--------
- :class:`TTLCache`: lightweight, async-aware TTL cache with hit/miss/expiration/
  eviction statistics, optional ``maxsize``, and optional Redis-backed expiry.
- Entity resolvers (:func:`ensure_user`, :func:`ensure_member`,
  :func:`ensure_channel`, :func:`ensure_role`, :func:`ensure_guild`) that:
  1) check in-memory cache,
  2) fall back to ``bot.get_*``,
  3) fall back to REST (``fetch_*``) when allowed,
  4) record telemetry on hard failures (Role/Guild).
- DB hydration for core models via :func:`fetch_db_user` / :func:`fetch_db_guild`.

Design
------
- TTL and eviction are evaluated against ``time.monotonic()`` to avoid clock
  skew issues. Expired entries are lazily purged on :meth:`TTLCache.get` and
  proactively pruned on :meth:`TTLCache.set`.
- If ``maxsize`` is defined and capacity is reached, the entry **closest to
  expiry** is evicted first (cheap heuristic for freshness).
- Caches are **process-local** for values but may mirror TTL markers to Redis
  (when configured) to keep expiry decisions consistent across processes.
- Telemetry is emitted on hard resolution failures for Guild/Role to aid ops.

Cache Keys & Defaults
---------------------
- Users: key = ``user_id`` (int), TTL 120s, max 5k
- Members: key = ``(guild_id, user_id)`` (tuple), TTL 120s, max 5k
- Channels: key = ``channel_id`` (int), TTL 300s, max 5k
- Roles: key = ``(guild_id, role_id)`` (tuple), TTL 300s, max 5k
- Guilds: key = ``guild_id`` (int), TTL 300s, max 2.5k
- Stickers: key = ``sticker_id`` (int), TTL 600s, max 5k

Examples
--------
Resolve a user and ensure the DB row exists::

    >>> db_user, u = await ensure_user(bot, 1234567890)
    >>> if u:
    ...     print(u.name)

Fetch a member, respecting cache with a custom TTL::

    >>> member = await ensure_member(bot, guild_id=111, user_id=222, ttl_seconds=30.0)

Invalidate on mutation::

    >>> invalidate_member(guild_id=111, user_id=222)

Notes
-----
- These helpers **do not** raise on common REST failure cases; they typically
  return ``None`` after logging/telemetry (except for DB ensure calls which
  can bubble DB errors).
- For rate-sensitive paths, prefer cached entities and avoid REST loops.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import pickle
import time
from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

import disnake
from loguru import logger
from redis.exceptions import RedisError
from spooky.core import messages
from spooky.core.exceptions import EntityResolutionError as EntityResolutionErrorType
from spooky.core.telemetry import send_exception
from spooky.redis import get_client as get_redis_client

from .utils import fetch_db_guild, fetch_db_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from spooky.bot import Spooky

    from .base_models.user import User

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class CacheStats:
    """Basic hit/miss/expiration/eviction accounting for a cache.

    Attributes
    ----------
    hits
        Number of successful :py:meth:`get` lookups that returned a live entry.
    misses
        Number of :py:meth:`get` calls that did not return a value (missing/expired).
    expirations
        Number of entries removed due to TTL expiry (from purge or read path).
    evictions
        Number of entries removed to make room when hitting ``maxsize``.
    """

    hits: int = 0
    misses: int = 0
    expirations: int = 0
    evictions: int = 0


class TTLCache(Generic[K, V]):
    """A tiny, async-aware TTL cache with optional Redis-backed storage.

    Parameters
    ----------
    name : str
        Human-readable cache name (used for diagnostics/logging).
    default_ttl : float
        Default TTL (seconds) applied when ``ttl`` is not supplied on :meth:`set`.
        Must be greater than zero.
    maxsize : int | None, optional
        Capacity ceiling. When full, the entry with the **nearest expiry**
        is evicted (simple freshness heuristic). ``None`` disables size limits.
    redis_prefix : str | None, optional
        Key prefix enabling Redis mode. When provided **and** a Redis manager is
        initialised, cache entries are stored in Redis with native PX TTL and a
        sorted-set index. When omitted, values remain process-local.

    Notes
    -----
    - Local mode stores ``(value, expires_monotonic)`` in a dict keyed by ``K``.
    - Redis mode pickles values to ``SET`` with ``PX=ttl`` and mirrors expiry
      as an absolute epoch into a ZSET for bulk trims and maxsize enforcement.
    """

    __slots__ = (
        "_approx_size",
        "_default_ttl",
        "_local_store",
        "_maxsize",
        "_name",
        "_pending_tasks",
        "_redis_prefix",
        "_stats",
    )

    def __init__(
        self,
        *,
        name: str,
        default_ttl: float,
        maxsize: int | None = None,
        redis_prefix: str | None = None,
    ) -> None:
        if default_ttl <= 0:
            raise ValueError("default_ttl must be greater than zero")
        self._name = name
        self._default_ttl = float(default_ttl)
        self._maxsize = maxsize
        self._redis_prefix = redis_prefix
        self._local_store: dict[K, tuple[V, float]] = {}
        self._stats = CacheStats()
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._approx_size = 0

    # ---------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Diagnostic name of this cache.

        Returns
        -------
        str
            The name passed at construction time.
        """
        return self._name

    @property
    def stats(self) -> CacheStats:
        """Cumulative statistics for this cache instance.

        Returns
        -------
        CacheStats
            Hit/miss/expiration/eviction counters since construction or last
            :py:meth:`clear` (note that :py:meth:`clear` resets stats).
        """
        return self._stats

    # ---------------------------------------------------------------------
    # Redis helpers
    # ---------------------------------------------------------------------

    def _redis_client(self) -> Redis | None:
        """Return the active Redis client if Redis integration is enabled.

        Returns
        -------
        redis.asyncio.Redis | None
            A client if ``redis_prefix`` was provided and a manager is configured,
            otherwise ``None``.
        """
        if self._redis_prefix is None:
            return None
        try:
            return get_redis_client()
        except RuntimeError:
            return None

    def _serialize_key(self, key: K) -> str:
        """Serialize a Python key ``K`` into a compact base64 member string.

        Parameters
        ----------
        key : K
            Cache key to serialize.

        Returns
        -------
        str
            A stable base64 representation suitable as a ZSET member / key suffix.
        """
        raw = pickle.dumps(key, protocol=pickle.HIGHEST_PROTOCOL)
        return base64.b64encode(raw).decode("ascii")

    def _decode_member(self, raw: bytes | str) -> str:
        """Decode a Redis ZSET member to ``str``."""
        return raw if isinstance(raw, str) else raw.decode("ascii")

    def _redis_value_key(self, serialized_key: str) -> str:
        """Compute the Redis key storing the pickled value payload.

        Parameters
        ----------
        serialized_key : str
            Result from :py:meth:`_serialize_key`.

        Returns
        -------
        str
            Fully-qualified Redis key for the value blob.

        Raises
        ------
        RuntimeError
            If this cache was constructed without ``redis_prefix``.
        """
        if self._redis_prefix is None:  # pragma: no cover - defensive
            raise RuntimeError("Redis prefix is not configured for this cache.")
        return f"{self._redis_prefix}:value:{serialized_key}"

    def _redis_index_key(self) -> str:
        """Compute the Redis ZSET key that indexes absolute expirations.

        Returns
        -------
        str
            Redis key of the ZSET mapping serialized keys → absolute expiry.

        Raises
        ------
        RuntimeError
            If this cache was constructed without ``redis_prefix``.
        """
        if self._redis_prefix is None:  # pragma: no cover - defensive
            raise RuntimeError("Redis prefix is not configured for this cache.")
        return f"{self._redis_prefix}:index"

    def _schedule(self, coro: Coroutine[object, object, None]) -> None:
        """Fire-and-forget a small Redis maintenance coroutine.

        Parameters
        ----------
        coro : Coroutine[object, object, None]
            The coroutine to run in the background.

        Notes
        -----
        - Best-effort only: failures are logged at DEBUG and otherwise ignored.
        - Pending tasks are tracked to avoid unbounded growth.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(coro)
        self._pending_tasks.add(task)

        def _cleanup(done: asyncio.Task[None]) -> None:
            self._pending_tasks.discard(done)
            with contextlib.suppress(asyncio.CancelledError):
                exc = done.exception()
                if exc is not None:
                    logger.debug("TTLCache[{}]: redis task error: {}", self._name, exc)

        task.add_done_callback(_cleanup)

    # ---------------------------------------------------------------------
    # Public cache API
    # ---------------------------------------------------------------------

    def clear(self) -> None:
        """Drop all entries and reset statistics to zero.

        Notes
        -----
        - In Redis mode, schedules a namespace/index clear; local state is reset
          immediately.
        """
        self._local_store.clear()
        self._stats = CacheStats()
        self._approx_size = 0
        redis = self._redis_client()
        if redis is None:
            return
        self._schedule(self._redis_clear(redis))

    def invalidate(self, key: K) -> None:
        """Remove a single key from the cache (no-op if absent).

        Parameters
        ----------
        key : K
            The cache key to remove.

        Notes
        -----
        - In Redis mode, schedules deletion of the value blob and index member.
        """
        self._local_store.pop(key, None)
        self._approx_size = len(self._local_store)
        redis = self._redis_client()
        if redis is None or self._redis_prefix is None:
            return
        serialized = self._serialize_key(key)
        self._schedule(self._redis_invalidate(redis, serialized))

    def invalidate_many(self, keys: Iterable[K]) -> None:
        """Remove multiple keys from the cache (no-ops if absent).

        Parameters
        ----------
        keys : Iterable[K]
            Keys to invalidate.

        Notes
        -----
        - Batches the Redis deletions for efficiency when Redis mode is enabled.
        """
        redis = self._redis_client()
        serialized_keys: list[str] = []
        for key in keys:
            self._local_store.pop(key, None)
            if self._redis_prefix is not None:
                serialized_keys.append(self._serialize_key(key))
        self._approx_size = len(self._local_store)
        if not serialized_keys or redis is None or self._redis_prefix is None:
            return
        self._schedule(self._redis_invalidate_many(redis, serialized_keys))

    def _purge_expired(self) -> int:
        """Remove all entries whose expiry is in the past.

        Returns
        -------
        int
            Number of entries removed in local mode. In Redis mode returns ``0``
            because trimming is scheduled asynchronously.
        """
        redis = self._redis_client()
        if redis is not None and self._redis_prefix is not None:
            self._schedule(self._trim_expired(redis))
            return 0
        return self._purge_expired_local()

    def _purge_expired_local(self) -> int:
        """Local-only expiry sweep using ``time.monotonic()``.

        Returns
        -------
        int
            Number of expired entries removed from the in-process store.
        """
        now = time.monotonic()
        removed = 0
        for key, (_value, expires_at) in list(self._local_store.items()):
            if expires_at < now:
                self._local_store.pop(key, None)
                removed += 1
                self._stats.expirations += 1
        if removed:
            self._approx_size = len(self._local_store)
        return removed

    def _evict_one_local(self) -> None:
        """Evict the entry that expires the soonest (freshness heuristic)."""
        if not self._local_store:
            return
        key_to_remove = min(self._local_store.items(), key=lambda item: item[1][1])[0]
        self._local_store.pop(key_to_remove, None)
        self._stats.evictions += 1
        self._approx_size = len(self._local_store)

    async def get(self, key: K) -> V | None:
        """Return the value for ``key`` if present and not expired; else ``None``.

        Parameters
        ----------
        key : K
            Cache key to look up.

        Returns
        -------
        V | None
            The cached value, or ``None`` if missing or expired.

        Side Effects
        ------------
        - Increments :pyattr:`CacheStats.hits` or :pyattr:`CacheStats.misses`.
        - May increment :pyattr:`CacheStats.expirations` if an expired entry is observed.
        """
        redis = self._redis_client()
        if redis is None or self._redis_prefix is None:
            return self._get_local(key)
        return await self._get_redis(redis, key)

    def _get_local(self, key: K) -> V | None:
        """Fast-path local lookup used by :py:meth:`get` when Redis is disabled."""
        entry = self._local_store.get(key)
        if entry is None:
            self._stats.misses += 1
            return None
        value, expires_at = entry
        now = time.monotonic()
        if expires_at < now:
            self._local_store.pop(key, None)
            self._approx_size = len(self._local_store)
            self._stats.misses += 1
            self._stats.expirations += 1
            return None
        self._stats.hits += 1
        return value

    async def _get_redis(self, redis: Redis, key: K) -> V | None:
        """Redis-backed lookup used by :py:meth:`get`.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.
        key : K
            Cache key.

        Returns
        -------
        V | None
            The cached value, or ``None`` if not present.

        Notes
        -----
        - If the payload is missing or corrupted, the ZSET index entry is tidied.
        - On Redis I/O errors, falls back to the local store.
        """
        serialized = self._serialize_key(key)
        value_key = self._redis_value_key(serialized)
        index_key = self._redis_index_key()
        try:
            payload = await redis.get(value_key)
        except RedisError as exc:
            logger.debug("TTLCache[{}]: redis GET failed: {}", self._name, exc)
            return self._get_local(key)
        if payload is None:
            self._stats.misses += 1
            try:
                removed = await redis.zrem(index_key, serialized)
            except RedisError as exc:  # pragma: no cover - defensive fallback
                logger.debug("TTLCache[{}]: redis ZREM failed: {}", self._name, exc)
            else:
                if removed:
                    self._stats.expirations += int(removed)
                    try:
                        self._approx_size = await redis.zcard(index_key)
                    except RedisError as exc:  # pragma: no cover - defensive fallback
                        logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)
            return None
        try:
            value = pickle.loads(payload)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis payload decode failed: {}", self._name, exc)
            self._stats.misses += 1
            try:
                await redis.delete(value_key)
                await redis.zrem(index_key, serialized)
                self._approx_size = await redis.zcard(index_key)
            except RedisError as redis_exc:  # pragma: no cover - defensive fallback
                logger.debug("TTLCache[{}]: redis cleanup failed: {}", self._name, redis_exc)
            return None
        self._stats.hits += 1
        return value

    async def set(self, key: K, value: V, *, ttl: float | None = None) -> None:
        """Insert or update a value with an optional per-item TTL.

        Parameters
        ----------
        key : K
            Key to set.
        value : V
            Value to cache.
        ttl : float | None, keyword-only
            TTL in seconds for this item. Defaults to ``default_ttl`` for the cache.

        Notes
        -----
        - Local mode purges expired entries and may evict one entry if ``maxsize``
          is reached before inserting the new value.
        - Redis mode uses PX TTL and a ZSET index, trims already-expired keys, and
          enforces ``maxsize`` globally (per-prefix) before updating size hints.
        """
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        redis = self._redis_client()
        if redis is None or self._redis_prefix is None:
            self._set_local(key, value, ttl_seconds)
            return
        await self._set_redis(redis, key, value, ttl_seconds)

    def _set_local(self, key: K, value: V, ttl_seconds: float) -> None:
        """Local-mode implementation of :py:meth:`set`.

        Parameters
        ----------
        key : K
            Key to set.
        value : V
            Value to cache.
        ttl_seconds : float
            Per-item TTL in seconds (already resolved).
        """
        self._purge_expired_local()
        if self._maxsize is not None and len(self._local_store) >= self._maxsize:
            self._evict_one_local()
        expiry = time.monotonic() + ttl_seconds
        self._local_store[key] = (value, expiry)
        self._approx_size = len(self._local_store)

    async def _set_redis(self, redis: Redis, key: K, value: V, ttl_seconds: float) -> None:
        """Redis-backed implementation of :py:meth:`set`.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.
        key : K
            Key to set.
        value : V
            Value to cache.
        ttl_seconds : float
            Per-item TTL in seconds.

        Notes
        -----
        - Serializes the value via pickle.
        - Writes the payload with ``PX`` TTL and updates the ZSET index with the
          absolute expiry. Then enforces ``maxsize`` and updates size hints.
        - On Redis failure, falls back to local store.
        """
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug(
                "TTLCache[{}]: pickle dump failed, falling back to local store: {}", self._name, exc
            )
            self._set_local(key, value, ttl_seconds)
            return

        serialized = self._serialize_key(key)
        value_key = self._redis_value_key(serialized)
        index_key = self._redis_index_key()
        expiry = time.time() + ttl_seconds
        ttl_ms = max(int(ttl_seconds * 1000), 1)

        # trim expired first to keep the index lean
        await self._trim_expired(redis)

        try:
            pipeline = redis.pipeline()
            pipeline.set(value_key, payload, px=ttl_ms)
            pipeline.zadd(index_key, {serialized: expiry})
            await pipeline.execute()
        except RedisError as exc:
            logger.debug("TTLCache[{}]: redis pipeline SET/ZADD failed: {}", self._name, exc)
            self._set_local(key, value, ttl_seconds)
            return

        # remove any stale local echo of this key and enforce maxsize globally
        self._local_store.pop(key, None)
        await self._enforce_redis_maxsize(redis)
        try:
            self._approx_size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)

    async def _trim_expired(self, redis: Redis) -> None:
        """Delete all keys whose absolute expiry is already in the past.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.

        Side Effects
        ------------
        - Deletes payload keys and removes members from the index ZSET.
        - Increments :pyattr:`CacheStats.expirations` for removed members.
        - Updates internal approximate size hint.
        """
        index_key = self._redis_index_key()
        now = time.time()
        try:
            expired = await redis.zrangebyscore(index_key, "-inf", now)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZRANGEBYSCORE failed: {}", self._name, exc)
            return
        if not expired:
            return
        serialized_keys = [self._decode_member(member) for member in expired]
        value_keys = [self._redis_value_key(serialized) for serialized in serialized_keys]
        try:
            if value_keys:
                await redis.delete(*value_keys)
            removed = await redis.zrem(index_key, *serialized_keys)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis cleanup failed: {}", self._name, exc)
            return
        if removed:
            self._stats.expirations += int(removed)
        try:
            self._approx_size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)

    async def _enforce_redis_maxsize(self, redis: Redis) -> None:
        """Evict oldest (soonest-to-expire) entries until size <= ``maxsize``.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.

        Notes
        -----
        - If ``maxsize`` is ``None``, this is a no-op.
        - Evicts by removing ZSET's lowest-ranked member and deleting its payload.
        """
        if self._maxsize is None:
            return
        index_key = self._redis_index_key()
        try:
            size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)
            return
        while size > self._maxsize:
            try:
                victims = await redis.zrange(index_key, 0, 0, withscores=False)
            except RedisError as exc:  # pragma: no cover - defensive fallback
                logger.debug("TTLCache[{}]: redis ZRANGE failed: {}", self._name, exc)
                return
            if not victims:
                break
            victim_serialized = self._decode_member(victims[0])
            value_key = self._redis_value_key(victim_serialized)
            try:
                pipeline = redis.pipeline()
                pipeline.delete(value_key)
                pipeline.zrem(index_key, victim_serialized)
                await pipeline.execute()
            except RedisError as exc:  # pragma: no cover - defensive fallback
                logger.debug("TTLCache[{}]: redis eviction cleanup failed: {}", self._name, exc)
                return
            self._stats.evictions += 1
            size -= 1
        try:
            self._approx_size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)

    async def _redis_clear(self, redis: Redis) -> None:
        """Delete all keys for this cache prefix from Redis.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.

        Notes
        -----
        - Removes all payload keys referenced by the index, then deletes the index.
        - Resets the internal approximate size to zero.
        """
        index_key = self._redis_index_key()
        try:
            members = await redis.zrange(index_key, 0, -1)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZRANGE failed: {}", self._name, exc)
            return
        serialized_keys = [self._decode_member(member) for member in members]
        value_keys = [self._redis_value_key(serialized) for serialized in serialized_keys]
        try:
            if value_keys:
                await redis.delete(*value_keys)
            await redis.delete(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis CLEAR failed: {}", self._name, exc)
            return
        self._approx_size = 0

    async def _redis_invalidate(self, redis: Redis, serialized_key: str) -> None:
        """Delete a single cached entry from Redis.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.
        serialized_key : str
            Key produced by :py:meth:`_serialize_key`.
        """
        value_key = self._redis_value_key(serialized_key)
        index_key = self._redis_index_key()
        try:
            pipeline = redis.pipeline()
            pipeline.delete(value_key)
            pipeline.zrem(index_key, serialized_key)
            await pipeline.execute()
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis invalidate failed: {}", self._name, exc)
            return
        try:
            self._approx_size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)

    async def _redis_invalidate_many(self, redis: Redis, serialized_keys: list[str]) -> None:
        """Batch-delete multiple cached entries from Redis.

        Parameters
        ----------
        redis : redis.asyncio.Redis
            Active client.
        serialized_keys : list[str]
            List of :py:meth:`_serialize_key` results to remove.
        """
        if not serialized_keys:
            return
        index_key = self._redis_index_key()
        value_keys = [self._redis_value_key(serialized) for serialized in serialized_keys]
        try:
            pipeline = redis.pipeline()
            if value_keys:
                pipeline.delete(*value_keys)
            pipeline.zrem(index_key, *serialized_keys)
            await pipeline.execute()
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis invalidate_many failed: {}", self._name, exc)
            return
        try:
            self._approx_size = await redis.zcard(index_key)
        except RedisError as exc:  # pragma: no cover - defensive fallback
            logger.debug("TTLCache[{}]: redis ZCARD failed: {}", self._name, exc)

    def snapshot(self) -> Mapping[K, tuple[V, float]]:
        """Return a shallow copy of the local store for diagnostics.

        Returns
        -------
        Mapping[K, tuple[V, float]]
            A mapping of keys to ``(value, expires_at_monotonic)``.

        Raises
        ------
        RuntimeError
            If Redis mode is enabled (snapshot is only for local mode).
        """
        if self._redis_prefix is not None and self._redis_client() is not None:
            raise RuntimeError("snapshot is not available for Redis-backed caches")
        return dict(self._local_store)

    def __len__(self) -> int:  # pragma: no cover - trivial
        """Return approximate size: local dict size or Redis index size."""
        return self._approx_size


_user_cache = TTLCache[int, disnake.User](
    name="user", default_ttl=120.0, maxsize=5000, redis_prefix="spooky:cache:user"
)
_member_cache = TTLCache[tuple[int, int], disnake.Member](
    name="member",
    default_ttl=120.0,
    maxsize=5000,
    redis_prefix="spooky:cache:member",
)
_channel_cache = TTLCache[
    int,
    disnake.abc.GuildChannel | disnake.abc.PrivateChannel | disnake.Thread,
](name="channel", default_ttl=300.0, maxsize=5000, redis_prefix="spooky:cache:channel")
_role_cache = TTLCache[tuple[int, int], disnake.Role](
    name="role", default_ttl=300.0, maxsize=5000, redis_prefix="spooky:cache:role"
)
_guild_cache = TTLCache[int, disnake.Guild](
    name="guild", default_ttl=300.0, maxsize=2500, redis_prefix="spooky:cache:guild"
)
_sticker_cache = TTLCache[int, disnake.sticker.Sticker](
    name="sticker", default_ttl=600.0, maxsize=5000, redis_prefix="spooky:cache:sticker"
)

_emoji_cache = TTLCache[int, disnake.Emoji | disnake.PartialEmoji](
    name="emoji", default_ttl=600.0, maxsize=5000, redis_prefix="spooky:cache:emoji"
)


async def ensure_user(
    bot: Spooky,
    user_id: int,
    *,
    ttl_seconds: float | None = None,
) -> tuple[User, disnake.User | None]:
    """Ensure the DB :class:`User` row exists and resolve the live ``disnake.User``.

    Resolution Order
    ----------------
    1. in-memory cache,
    2. :py:meth:`disnake.Client.get_user`,
    3. :py:meth:`disnake.Client.fetch_user` (REST).

    Parameters
    ----------
    bot : Spooky
        The running bot instance.
    user_id : int
        Discord user snowflake.
    ttl_seconds : float | None, optional
        TTL override (seconds) for the resolved user entry.

    Returns
    -------
    tuple[User, disnake.User | None]
        The ensured DB user row and the resolved live user (or ``None`` if not
        accessible).

    Notes
    -----
    REST failures are logged at DEBUG level; resolution returns gracefully.
    """
    db_user: User = await fetch_db_user(user_id)

    cached = await _user_cache.get(user_id)
    if cached is not None:
        return db_user, cached

    user: disnake.User | None = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except (disnake.NotFound, disnake.HTTPException) as exc:
            logger.debug("ensure_user: fetch_user failed for {}: {}", user_id, exc)
            user = None

    if user is not None:
        await _user_cache.set(user_id, user, ttl=ttl_seconds)

    return db_user, user


async def ensure_sticker(
    bot: Spooky,
    sticker_id: int,
    *,
    ttl_seconds: float | None = None,
) -> disnake.sticker.Sticker | None:
    """Resolve a :class:`disnake.sticker.Sticker` and cache it."""
    cached = await _sticker_cache.get(sticker_id)
    if cached is not None:
        return cached

    sticker: disnake.sticker.Sticker | None = bot.get_sticker(sticker_id)

    if sticker is None:
        try:
            sticker = await bot.fetch_sticker(sticker_id)
        except (
            disnake.NotFound,
            disnake.Forbidden,
            disnake.HTTPException,
        ) as exc:
            logger.debug("ensure_sticker: fetch_sticker failed for {}: {}", sticker_id, exc)
            sticker = None

    if sticker is not None:
        await _sticker_cache.set(sticker_id, sticker, ttl=ttl_seconds)

    return sticker


async def ensure_emoji(
    bot: Spooky,
    emoji_id: int,
    *,
    guild_id: int | None = None,
    name: str | None = None,
    animated: bool | None = None,
    ttl_seconds: float | None = None,
) -> disnake.Emoji | disnake.PartialEmoji:
    """Resolve a :class:`disnake.Emoji` and cache it.

    Resolution relies on in-memory caches only to avoid API calls. When the
    emoji cannot be found, a ``PartialEmoji`` is constructed using the provided
    metadata so callers can still render the custom emoji markup.
    """
    cached = await _emoji_cache.get(emoji_id)
    if cached is not None:
        return cached

    emoji: disnake.Emoji | disnake.PartialEmoji | None = None

    if guild_id is not None:
        guild = bot.get_guild(guild_id)
        if guild:
            emoji = disnake.utils.get(guild.emojis, id=emoji_id)

    if emoji is None:
        emoji = next((e for e in bot.emojis if e.id == emoji_id), None)

    if emoji is None:
        emoji = disnake.PartialEmoji(name=name or "emoji", id=emoji_id, animated=bool(animated))

    await _emoji_cache.set(emoji_id, emoji, ttl=ttl_seconds)
    return emoji


async def ensure_member(
    bot: Spooky,
    guild_id: int,
    user_id: int,
    *,
    ttl_seconds: float | None = None,
) -> disnake.Member | None:
    """Resolve a :class:`disnake.Member` for ``(guild_id, user_id)``.

    Resolution Order
    ----------------
    1. in-memory cache,
    2. ``bot.get_guild`` (or ``bot.fetch_guild``) to scope,
    3. ``Guild.get_member`` (or ``Guild.fetch_member``).

    Parameters
    ----------
    bot : Spooky
        The running bot instance.
    guild_id : int
        Discord guild snowflake.
    user_id : int
        Discord user snowflake.
    ttl_seconds : float | None, optional
        TTL override (seconds) for the resolved member.

    Returns
    -------
    disnake.Member | None
        The member or ``None`` if not accessible (e.g., missing perms).
    """
    key = (guild_id, user_id)
    cached = await _member_cache.get(key)
    if cached is not None:
        return cached

    member: disnake.Member | None = None
    guild = bot.get_guild(guild_id)
    if guild is None:
        try:
            guild = await bot.fetch_guild(guild_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as exc:
            logger.debug("ensure_member: fetch_guild failed for {}: {}", guild_id, exc)
            guild = None

    if guild is not None:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (disnake.NotFound, disnake.HTTPException, disnake.Forbidden) as exc:
                logger.debug(
                    "ensure_member: fetch_member failed for {}/{}: {}", guild_id, user_id, exc
                )
                member = None

    if member is not None:
        await _member_cache.set(key, member, ttl=ttl_seconds)
    return member


async def ensure_channel(
    bot: Spooky,
    channel_id: int,
    *,
    ttl_seconds: float | None = None,
) -> disnake.abc.GuildChannel | disnake.abc.PrivateChannel | disnake.Thread | None:
    """Resolve a channel (guild/private/thread) by ``channel_id``.

    Parameters
    ----------
    bot : Spooky
        The running bot instance.
    channel_id : int
        Discord channel snowflake.
    ttl_seconds : float | None, optional
        TTL override (seconds) for the resolved channel.

    Returns
    -------
    disnake.abc.GuildChannel | disnake.abc.PrivateChannel | disnake.Thread | None
        The resolved channel or ``None`` when not accessible.
    """
    cached = await _channel_cache.get(channel_id)
    if cached is not None:
        return cached

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as exc:
            logger.debug("ensure_channel: fetch_channel failed for {}: {}", channel_id, exc)
            channel = None

    if channel is not None:
        await _channel_cache.set(channel_id, channel, ttl=ttl_seconds)
    return channel


async def ensure_role(
    bot: Spooky,
    guild_id: int,
    role_id: int,
    *,
    ttl_seconds: float | None = None,
) -> disnake.Role | None:
    """Resolve a :class:`disnake.Role` for ``(guild_id, role_id)`` and cache it.

    On hard failures (unavailable guild or role), a telemetry exception is sent.

    Parameters
    ----------
    bot : Spooky
        The running bot instance.
    guild_id : int
        Discord guild snowflake.
    role_id : int
        Discord role snowflake.
    ttl_seconds : float | None, optional
        TTL override (seconds) for the resolved role.

    Returns
    -------
    disnake.Role | None
        The resolved role or ``None`` on failure (after telemetry).
    """
    key = (guild_id, role_id)
    cached = await _role_cache.get(key)
    if cached is not None:
        return cached

    guild = bot.get_guild(guild_id)
    if guild is None:
        try:
            guild = await bot.fetch_guild(guild_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as exc:
            logger.debug("ensure_role: fetch_guild failed for {}: {}", guild_id, exc)
            guild = None
    if guild is None:
        err = EntityResolutionErrorType(
            "Role", {"guild_id": guild_id, "role_id": role_id}, detail="guild unavailable"
        )
        title = messages.telemetry.entity_resolution_title.format(entity="Role")
        desc = messages.telemetry.entity_resolution_desc.format(
            entity="Role", identifiers=str({"guild_id": guild_id, "role_id": role_id})
        )
        await send_exception(bot, title=title, description=desc, error=err)
        return None

    role = guild.get_role(role_id)
    if role is None:
        try:
            roles = await guild.fetch_roles()
        except (disnake.Forbidden, disnake.HTTPException) as exc:
            logger.debug("ensure_role: fetch_roles failed for {}: {}", guild_id, exc)
            roles = []
        role = next((r for r in roles if r.id == role_id), None)

    if role is not None:
        await _role_cache.set(key, role, ttl=ttl_seconds)
        return role

    err = EntityResolutionErrorType(
        "Role", {"guild_id": guild_id, "role_id": role_id}, detail="cache+REST resolution failed"
    )
    title = messages.telemetry.entity_resolution_title.format(entity="Role")
    desc = messages.telemetry.entity_resolution_desc.format(
        entity="Role", identifiers=str({"guild_id": guild_id, "role_id": role_id})
    )
    await send_exception(bot, title=title, description=desc, error=err)
    return None


async def ensure_guild(
    bot: Spooky,
    guild_id: int,
    *,
    ttl_seconds: float | None = None,
) -> disnake.Guild | None:
    """Ensure the DB row exists and resolve a :class:`disnake.Guild`.

    Resolution Order
    ----------------
    1. DB hydrate via :func:`fetch_db_guild` (idempotent),
    2. cache,
    3. ``bot.get_guild``,
    4. ``bot.fetch_guild`` (REST),
    5. telemetry on hard failure.

    Parameters
    ----------
    bot : Spooky
        The running bot instance.
    guild_id : int
        Discord guild snowflake.
    ttl_seconds : float | None, optional
        TTL override (seconds) for the resolved guild.

    Returns
    -------
    disnake.Guild | None
        The resolved guild or ``None`` after telemetry on failure.
    """
    await fetch_db_guild(guild_id)
    cached = await _guild_cache.get(guild_id)
    if cached is not None:
        return cached

    guild = bot.get_guild(guild_id)
    if guild is None:
        try:
            guild = await bot.fetch_guild(guild_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as exc:
            logger.debug("ensure_guild: fetch_guild failed for {}: {}", guild_id, exc)
            guild = None

    if guild is not None:
        await _guild_cache.set(guild_id, guild, ttl=ttl_seconds)
        return guild

    err = EntityResolutionErrorType(
        "Guild", {"guild_id": guild_id}, detail="cache+REST resolution failed"
    )
    title = messages.telemetry.entity_resolution_title.format(entity="Guild")
    desc = messages.telemetry.entity_resolution_desc.format(
        entity="Guild", identifiers=str({"guild_id": guild_id})
    )
    await send_exception(bot, title=title, description=desc, error=err)
    return None


def invalidate_guild(guild_id: int) -> None:
    """Invalidate a guild entry by ``guild_id``.

    Parameters
    ----------
    guild_id : int
        Guild to invalidate.
    """
    _guild_cache.invalidate(guild_id)


def invalidate_member(guild_id: int, user_id: int) -> None:
    """Invalidate a member entry by ``(guild_id, user_id)``.

    Parameters
    ----------
    guild_id : int
        Guild ID that scopes the member.
    user_id : int
        User ID for the member to remove.
    """
    _member_cache.invalidate((guild_id, user_id))


def invalidate_user(user_id: int) -> None:
    """Invalidate a user entry by ``user_id``.

    Parameters
    ----------
    user_id : int
        User to invalidate.
    """
    _user_cache.invalidate(user_id)


def invalidate_role(guild_id: int, role_id: int) -> None:
    """Invalidate a role entry by ``(guild_id, role_id)``.

    Parameters
    ----------
    guild_id : int
        Guild ID that contains the role.
    role_id : int
        Role to invalidate.
    """
    _role_cache.invalidate((guild_id, role_id))


def invalidate_channel(channel_id: int) -> None:
    """Invalidate a channel entry by ``channel_id``.

    Parameters
    ----------
    channel_id : int
        Channel to invalidate.
    """
    _channel_cache.invalidate(channel_id)


__all__ = [
    "CacheStats",
    "TTLCache",
    "ensure_channel",
    "ensure_emoji",
    "ensure_guild",
    "ensure_member",
    "ensure_role",
    "ensure_sticker",
    "ensure_user",
    "invalidate_channel",
    "invalidate_guild",
    "invalidate_member",
    "invalidate_role",
    "invalidate_user",
]
