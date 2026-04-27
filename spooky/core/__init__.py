"""Centralized configuration & settings loader for Spooky.

This module wires together:

- **Environment variables** (via ``python-dotenv`` and direct ``os.getenv``),
- **Dynaconf-backed config** for *colors*, *emojis*, and *messages*,
- **Database configuration helpers** for SQLAlchemy (URL + engine options),
- **Redis connection helpers** for cache/TTL infrastructure,
- And exports convenient aliases for frequently accessed settings.

On import, it also validates that a **bot token** is available and configures
Disnake's default embed color from settings.

Exports
-------
settings : Dynaconf
    Root settings object with structured groups (``bot``, ``log``, ``emojis``,
    ``colors``, ``messages``).
emojis : Mapping[str, str]
    Emoji shortcuts loaded from ``assets/settings/emojis.toml`` and accessible as
    both mapping keys and attributes (``emojis.checkmark``).
colors : Mapping[str, int]
    Color constants loaded from ``assets/settings/colors.toml`` and accessible
    as both mapping keys and attributes (``colors.green``).
messages : Mapping[str, Any]
    App message strings from ``assets/settings/messages.toml`` (supports nested
    groups like ``messages.telemetry.details_title``).
get_redis_url : Callable[[], str]
    Compose a Redis URL from either ``REDIS_URL`` or granular ``REDIS_*`` parts.
get_redis_options : Callable[[], dict[str, Any]]
    Return supplemental keyword arguments for :func:`redis.asyncio.Redis.from_url`.

Environment
-----------
General
~~~~~~~
- ``.env`` is loaded first with ``load_dotenv(override=True)``.
- Dynaconf reads settings files under ``assets/settings``:
  - ``colors.toml``, ``emojis.toml``, ``messages.toml``.
- Dynaconf prefix: ``SPOOKY_`` (e.g., ``SPOOKY_LOG__LEVEL=DEBUG`` for ``settings.log.level``).

Bot / Logging
~~~~~~~~~~~~~
- ``SPOOKY_BOT__TOKEN`` : Bot token (validated at import time).
- ``SPOOKY_LOG__LEVEL`` : Default log level (e.g., ``INFO``, ``DEBUG``).

Database (URL & Engine)
~~~~~~~~~~~~~~~~~~~~~~~
- ``DATABASE_URL`` : Full SQLAlchemy URL (overrides all other DB_* vars).
- ``DB_DRIVER`` : SQLAlchemy async driver (default: ``postgresql+asyncpg``).
- ``DB_HOST`` (default: ``db``), ``DB_PORT`` (``5432``),
  ``DB_USER`` (``spooky``), ``DB_PASS`` (``spooky``), ``DB_NAME`` (``spookydb``).
- Engine tuning:
  - ``DB_ECHO`` (bool): SQL echo.
  - ``DB_POOL_SIZE`` (int), ``DB_MAX_OVERFLOW`` (int),
  - ``DB_POOL_TIMEOUT`` (int), ``DB_POOL_RECYCLE`` (int).

Redis
~~~~~
- ``REDIS_URL`` : Full connection URL (overrides other Redis env vars).
- ``REDIS_HOST`` (default: ``redis``), ``REDIS_PORT`` (``6379``),
  ``REDIS_DB`` (``0``), ``REDIS_USER`` (optional), ``REDIS_PASS`` (optional),
  ``REDIS_SSL`` (bool: enable TLS).

Examples
--------
Get a database URL (respecting ``DATABASE_URL`` if set):

>>> url = get_database_url()

Build engine options from env:

>>> opts = get_database_engine_options()
>>> # pass into sqlalchemy.create_async_engine(url, **opts)

Access emojis/colors/messages:

>>> emojis.checkmark, colors.green, messages.telemetry.details_title

Notes
-----
- When DB env vars are missing, :func:`get_credentials` logs that Docker-friendly
  defaults were applied (host=db, db=spookydb, user=spooky).
- Import-time safety checks:
  - Raises ``RuntimeError`` if the bot token is missing.
  - Sets :meth:`disnake.Embed.set_default_colour` from ``settings.colors.embed``.
"""

import os
from collections import abc
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import disnake
from dotenv import load_dotenv
from dynaconf import Dynaconf
from loguru import logger

__all__ = [
    "colors",
    "emojis",
    "get_credentials",
    "get_database_engine_options",
    "get_database_url",
    "get_redis_options",
    "get_redis_url",
    "messages",
    "settings",
]

if TYPE_CHECKING:
    from dataclasses import dataclass

    @dataclass
    class _BotGroup:
        token: str
        secret: str
        client_id: str
        env: str

    @dataclass
    class _LogGroup:
        level: str

    class _EmojiGroup(abc.Mapping[str, str]):
        def __getattr__(self, name: str) -> str: ...

    class _ColorGroup(abc.Mapping[str, int]):
        def __getattr__(self, name: str) -> int: ...

    class _GroupStr(abc.Mapping[str, str]):
        def __getattr__(self, name: str) -> str: ...

    class _TelemetryGroup(abc.Mapping[str, str]):
        details_title: str
        entity_resolution_title: str
        entity_resolution_desc: str

        def __getattr__(self, name: str) -> str: ...

    class _MessagesGroup(abc.Mapping[str, object]):
        exceptions: _GroupStr
        errors: _GroupStr
        moderation: _GroupStr
        defaults: _GroupStr
        kick: _GroupStr
        ban: _GroupStr
        unban: _GroupStr
        case: _GroupStr
        telemetry: _TelemetryGroup

        def __getattr__(self, name: str) -> object: ...

    @dataclass
    class Settings:
        bot: _BotGroup
        log: _LogGroup

        emojis: _EmojiGroup
        colors: _ColorGroup
        messages: _MessagesGroup


# Load .env first so Dynaconf can see override values
load_dotenv(override=True)

settings = cast(
    "Settings",
    Dynaconf(
        envvar_prefix="SPOOKY",
        load_dotenv=True,
        merge_enabled=True,
        settings_files=[
            "assets/settings/colors.toml",
            "assets/settings/emojis.toml",
            "assets/settings/messages.toml",
        ],
    ),
)


def _env_bool(name: str) -> bool | None:
    """Return a tri-state boolean parsed from an environment variable.

    Parameters
    ----------
    name : str
        Environment variable name.

    Returns
    -------
    bool | None
        ``True`` for values in {1, true, yes, on}, ``False`` for other strings,
        and ``None`` if the variable is not set.
    """
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Convenient shortcuts
emojis = settings.emojis
colors = settings.colors
messages = settings.messages


def _env_int(name: str) -> int | None:
    """Parse an integer from an environment variable, or return ``None``.

    Parameters
    ----------
    name : str
        Environment variable name.

    Returns
    -------
    int | None
        The parsed integer, or ``None`` if unset or invalid (with a warning).
    """
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for {}={!r}; ignoring", name, value)
        return None


def get_credentials() -> dict[str, str]:
    """Build DB credentials from env with sensible Docker defaults.

    Environment
    -----------
    DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

    Returns
    -------
    dict[str, str]
        A dict with keys ``host``, ``port``, ``user``, ``password``, ``database``.

    Notes
    -----
    - Missing values fall back to Docker-friendly defaults and emit a single
      info log enumerating which environment variables were missing.
    """
    defaults = {
        "host": "db",
        "port": "5432",
        "user": "spooky",
        "password": "spooky",
        "database": "spookydb",
    }

    mapping = {
        "DB_HOST": "host",
        "DB_PORT": "port",
        "DB_USER": "user",
        "DB_PASS": "password",
        "DB_NAME": "database",
    }

    used_defaults: list[str] = []
    credentials: dict[str, str] = {}

    for env_key, key in mapping.items():
        value = os.getenv(env_key)
        if value is None or value == "":
            value = defaults[key]
            used_defaults.append(env_key)
        credentials[key] = value

    if used_defaults:
        logger.info(
            "DB env missing for {}; using Docker defaults (host={}, db={}, user={})",
            ", ".join(used_defaults),
            credentials["host"],
            credentials["database"],
            credentials["user"],
        )

    return credentials


def get_database_url(*, driver: str | None = None) -> str:
    """Return an SQLAlchemy database URL derived from environment configuration.

    Resolution order
    ----------------
    1. ``DATABASE_URL`` if set (returned as-is),
    2. Otherwise builds a URL from driver + credentials.

    Parameters
    ----------
    driver : str | None, optional
        SQLAlchemy async driver (e.g., ``"postgresql+asyncpg"``). When not
        provided, uses ``DB_DRIVER`` env or defaults to ``"postgresql+asyncpg"``.

    Returns
    -------
    str
        A fully composed database URL suitable for
        :func:`sqlalchemy.ext.asyncio.create_async_engine`.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    resolved_driver = driver or os.getenv("DB_DRIVER") or "postgresql+asyncpg"
    creds = get_credentials()
    return (
        f"{resolved_driver}://{creds['user']}:{creds['password']}"
        f"@{creds['host']}:{creds['port']}/{creds['database']}"
    )


def get_database_engine_options() -> dict[str, Any]:
    """Return keyword arguments for :func:`sqlalchemy.create_async_engine`.

    Reads optional tuning flags from the environment and converts them into
    engine kwargs. Unset or invalid values are ignored.

    Environment
    -----------
    DB_ECHO (bool)
    DB_POOL_SIZE (int)
    DB_MAX_OVERFLOW (int)
    DB_POOL_TIMEOUT (int)
    DB_POOL_RECYCLE (int)
    DB_POOL_LIMIT (int)

    Returns
    -------
    dict[str, Any]
        A dict of engine options (only keys present in env are included).
    """
    # Sensible defaults tuned for Discord-bot style workloads:
    #
    # - Small, **bounded** pool to avoid exhausting Postgres connections when
    #   multiple bot shards/processes run concurrently. SQLAlchemy's defaults
    #   allow a pool size of 5 with **10 overflow connections**, which can
    #   easily burst beyond typical managed Postgres limits. We default to a
    #   5-connection pool with **no overflow** so contention results in queue
    #   waits instead of new connections that trigger "too many clients".
    # - A moderate pool timeout keeps callers from hanging indefinitely when
    #   the pool is saturated.
    #
    # Environment variables can still override these values when needed.
    options: dict[str, Any] = {
        "pool_size": 5,
        "max_overflow": 0,
        "pool_timeout": 30,
    }

    echo_flag = _env_bool("DB_ECHO")
    if echo_flag is not None:
        options["echo"] = echo_flag

    for env, key in {
        "DB_POOL_SIZE": "pool_size",
        "DB_MAX_OVERFLOW": "max_overflow",
        "DB_POOL_TIMEOUT": "pool_timeout",
        "DB_POOL_RECYCLE": "pool_recycle",
    }.items():
        value = _env_int(env)
        if value is not None:
            options[key] = value

    pool_limit = _env_int("DB_POOL_LIMIT")
    if pool_limit is not None:
        # Avoid runaway per-process connection usage under heavy traffic by
        # clamping pool + overflow to a caller-specified ceiling.
        hard_limit = max(1, pool_limit)
        pool_size = options.get("pool_size", 5)
        max_overflow = options.get("max_overflow", 0)

        if pool_size > hard_limit:
            logger.warning(
                "pool_size capped at {hard_limit} (requested {pool_size})",
                hard_limit=hard_limit,
                pool_size=pool_size,
            )
            pool_size = hard_limit

        overflow_budget = max(0, hard_limit - pool_size)
        if max_overflow > overflow_budget:
            logger.warning(
                "max_overflow capped at {overflow_budget} (requested {max_overflow})",
                overflow_budget=overflow_budget,
                max_overflow=max_overflow,
            )
            max_overflow = overflow_budget

        options["pool_size"] = pool_size
        options["max_overflow"] = max_overflow

    return options


def get_redis_url() -> str:
    """Return a Redis connection URL derived from environment configuration.

    Resolution order
    ----------------
    1. ``REDIS_URL`` if set (returned as-is),
    2. Otherwise builds a URL from granular ``REDIS_*`` parts.

    Environment
    -----------
    REDIS_URL, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_USER, REDIS_PASS, REDIS_SSL

    Returns
    -------
    str
        A Redis connection URL suitable for :func:`redis.asyncio.Redis.from_url`.
    """
    url = os.getenv("REDIS_URL")
    if url:
        return url

    host = os.getenv("REDIS_HOST") or "redis"
    port = os.getenv("REDIS_PORT") or "6379"
    db = os.getenv("REDIS_DB") or "0"
    user = os.getenv("REDIS_USER")
    password = os.getenv("REDIS_PASS")
    ssl_flag = _env_bool("REDIS_SSL")
    scheme = "rediss" if ssl_flag else "redis"

    auth = ""
    if user or password:
        encoded_user = quote(user or "")
        encoded_pass = quote(password or "")
        if user and password:
            auth = f"{encoded_user}:{encoded_pass}@"
        elif user:
            auth = f"{encoded_user}@"
        else:
            auth = f":{encoded_pass}@"

    return f"{scheme}://{auth}{host}:{port}/{db}"


def get_redis_options() -> dict[str, Any]:
    """Return keyword arguments for :func:`redis.asyncio.Redis.from_url`.

    Currently supports enabling TLS regardless of URL scheme and supplying a
    password when ``REDIS_URL`` omits credentials.

    Returns
    -------
    dict[str, Any]
        Extra keyword arguments to pass to ``Redis.from_url``.
    """
    options: dict[str, Any] = {}

    redis_url_env = os.getenv("REDIS_URL")

    ssl_flag = _env_bool("REDIS_SSL")
    if ssl_flag:
        options["ssl"] = True

    if redis_url_env:
        password = os.getenv("REDIS_PASS")
        if password and "@" not in redis_url_env:
            options.setdefault("password", password)

        user = os.getenv("REDIS_USER")
        if user and "@" not in redis_url_env:
            options.setdefault("username", user)

    return options


# Validate critical config and set embed defaults
if not settings.bot.token:
    raise RuntimeError("The bot token is missing")

disnake.Embed.set_default_colour(settings.colors.embed)
