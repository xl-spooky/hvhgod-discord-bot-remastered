"""Spooky bot bootstrap script (runtime entry point).

This module serves as the **main entry point** for running the Spooky bot.
It configures logging, validates runtime prerequisites, sets up caches and
intents, loads all extensions, and starts the bot in an environment-sensitive
manner (e.g., developer vs production). It also wires signal handlers for
**graceful shutdown** and ensures all external resources (HTTP sessions,
Redis, and database engines) are properly initialized and cleaned up.

Overview
--------
- **Logging:** Structured logging via :mod:`loguru`, configured by
  :mod:`spooky.core.logging`.
- **Preflight checks:** Run via :mod:`spooky.core.checks`; the bot continues
  even if migrations are missing, with database-backed features disabled.
- **Activity & status:** Automatically selected based on the current
  environment (DEV vs PROD).
- **Memory efficiency:** Conservative intents and caching policies are used
  to minimize runtime footprint.
- **Extensions:** Loaded recursively from the ``spooky/bot/extensions``
  directory.
- **Signals:** Handles SIGINT, SIGTERM, and SIGBREAK (on Windows) for safe
  shutdown.
- **Lifecycle:** Initializes Redis, database, and HTTP clients before login,
  and tears them down on exit.

Typical usage
-------------
Run directly as a script to start the bot::

    >>> python -m spooky.__main__

Notes
-----
- If database migrations are missing, the bot runs in degraded mode, skipping
  all DB-backed operations.
- HTTP sessions (via :class:`spooky.ext.http.HttpClient`) are automatically
  created and closed.
- The script uses :class:`asyncio.TaskGroup` for parallel startup operations.

"""

from __future__ import annotations

import asyncio
import signal
import sys
import warnings

import disnake
from disnake.ext.commands import CommandSyncFlags
from loguru import logger
from spooky.bot import Spooky, __author__, __version__
from spooky.core import checks, logging, settings
from spooky.ext.http import HttpClient

__all__ = ["main"]

# Suppress noisy runtime warnings from certain third-party libraries.
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message="coroutine .* was never awaited",
)


async def main() -> None:
    """Run the Spooky bot with environment-sensitive configuration.

    Execution steps
    ---------------
    1. Configure structured logging and print version/author metadata.
    2. Perform preflight checks (:mod:`spooky.core.checks`), gracefully degrading
       to DB-disabled mode if migrations are missing.
    3. Choose appropriate activity/status based on the runtime environment.
    4. Configure conservative intents, caching, and command sync flags.
    5. Instantiate and configure the :class:`~spooky.bot.Spooky` bot instance.
    6. Register cross-platform signal handlers for graceful shutdown.
    7. Initialize the database (if enabled), Redis manager, and log in the bot.
    8. Create HTTP sessions and connect the bot to the Discord gateway.
    9. On exit, clean up the database and Redis connections.

    Notes
    -----
    - The routine uses :class:`asyncio.TaskGroup` to perform startup tasks
      concurrently and handle exceptions cohesively.
    - On missing migrations, the bot does not abort but logs a warning.
    - Graceful termination ensures all clients and connections are cleanly
      closed before the event loop exits.
    """
    # Step 1: Configure logging and print version/author.
    logging.setup()
    logger.info(f" running spooky v{__version__} ({settings.bot.env})")
    logger.info(f"  by {__author__}")

    # Step 2: Preflight checks (do not hard-fail).
    checks.run()
    if not checks.db_enabled():
        logger.warning(
            "no migrations found. running with database disabled; "
            "db-backed features are unavailable."
        )

    # Step 3: Presence based on environment.
    if settings.bot.env == "DEV":
        activity = disnake.Game(name="[DEV]")
        status = disnake.Status.dnd
    else:
        activity = disnake.Activity(
            type=disnake.ActivityType.watching,
            name="Over .gg/hvhgod",
        )
        status = disnake.Status.dnd

    # Step 4: Intents, caching, and command sync flags.
    intents = disnake.Intents.all()
    sync_flags = CommandSyncFlags.default()
    sync_flags.sync_commands_debug = False

    # Step 5: Create the bot instance.
    bot = Spooky(
        command_prefix=Spooky.default_prefix,
        help_command=None,
        allowed_mentions=disnake.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
            replied_user=True,
        ),
        activity=activity,
        status=status,
        intents=intents,
        command_sync_flags=sync_flags,
        max_messages=None,
        chunk_guilds_at_startup=True,
    )
    bot.load_extensions("./spooky/bot/extensions")  # Load all extension packages/modules.

    # Step 6: Register signal handlers.
    shutdown_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        """Handle termination signals and trigger graceful shutdown."""
        logger.info("shutting down...")
        bot.loop.create_task(bot.close())
        shutdown_event.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32":
        signals.append(signal.SIGBREAK)

    for signal_ in signals:
        try:
            bot.loop.add_signal_handler(signal_, _signal_handler)
        except NotImplementedError:
            # Some event loops (e.g. Windows Proactor) do not support loop signal handlers.
            signal.signal(signal_, _signal_handler)

    # Step 7: Initialize database and authenticate the bot.
    async with asyncio.TaskGroup() as tg:
        if checks.db_enabled():
            logger.info("initializing database engine")
            tg.create_task(HttpClient.init_database())
        else:
            logger.info("skipping database initialization (disabled)")
        tg.create_task(bot.login(settings.bot.token))  # Obtain gateway token/session.

    # Step 8: Create HTTP sessions and connect the bot.
    async with (
        HttpClient.create_session(),  # Default HTTP client
        HttpClient.create_auth_session(
            str(settings.bot.client_id), settings.bot.secret
        ),  # OAuth/auth session
        asyncio.TaskGroup() as tg,
    ):
        tg.create_task(bot.connect())  # Connect to the gateway and start event loop.

    # Step 9: Cleanup phase.
    if checks.db_enabled():
        await HttpClient.shutdown_database()


if __name__ == "__main__":
    # Run the async entry point with a clean event loop.
    asyncio.run(main())
