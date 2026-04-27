"""Spooky bot core class and extension discovery utilities.

This module defines the Spooky runtime core:

- Package metadata: :data:`__version__`, :data:`__author__`.
- :class:`Spooky`, a thin :class:`disnake.ext.commands.Bot` subclass that adds:
  - A small **connection delay** to reduce double-instance race conditions.
  - **Guarded event dispatch** (drops events until the bot is ready).
  - **Recursive extension discovery** and bulk loading helpers.
- :func:`_walk_modules`, a utility to enumerate importable modules under a package.

Typical usage
-------------
>>> bot = Spooky(...)
>>> bot.load_extensions("./spooky/bot/extensions")
>>> bot.run("TOKEN")

Design notes
------------
- **Connection delay**: adds a brief sleep prior to connecting to help rolling
  deployments avoid event handling overlap while a previous instance is still
  winding down.
- **Guarded dispatch**: drops events until ``is_ready()`` is true, except for
  ``on_ready`` itself. This mitigates handlers firing before caches and
  listeners are fully prepared.
- **Extension discovery**: supports filesystem paths *or* dotted module names,
  walks subpackages, and allows simple ignore predicates to exclude modules.

"""

from __future__ import annotations

# The version is supposed to follow this format:
# <major>.<minor>.<patch>-<YYYY>.<MM>.<DD>
# This is checked by CI and used in the release process.
# Please update it when making a release.
__version__ = "1.0.0-2025.//.//"
__author__ = "SPOOKY DEVELOPMENT INC"

import asyncio
import importlib
import importlib.util
import os
import pkgutil
from collections import abc
from traceback import format_exception
from typing import TYPE_CHECKING, Any, cast

import disnake
from disnake.ext import commands
from loguru import logger
from spooky.ext.patches import apply_container_view_store_patch

if TYPE_CHECKING:
    from spooky.premium.enums import PremiumProduct

from .context import SpookyContext
from .prefix import DEFAULT_PREFIX, get_effective_prefix

# Ensure our disnake view-store patch is installed early.
apply_container_view_store_patch()

__all__ = ["Spooky", "__author__", "__version__", "_walk_modules"]


class Spooky(commands.Bot):
    """Extend :class:`~disnake.ext.commands.Bot` with guarded dispatch and discovery.

    Adds safer event dispatching, application command tracing, and utilities for
    discovering and loading extensions.

    Attributes
    ----------
    cached_skus : dict[int, disnake.SKU]
        Cache of SKU objects.
    default_prefix : str
        Fallback prefix used by :meth:`get_prefix` when no overrides exist.
    connection_delay : float
        Time in seconds to delay the connection process (default: ``15.0``).
    _connected : bool
        Internal flag indicating whether an initial connection succeeded.

    Notes
    -----
    - :attr:`default_prefix` is initialized from :data:`spooky.bot.DEFAULT_PREFIX`.
    - The connection delay can be tuned per instance to accommodate deployment needs.
    """

    cached_skus: dict[int, disnake.SKU]
    sku_to_product: dict[int, PremiumProduct]
    product_to_sku: dict[PremiumProduct, int]
    default_prefix: str = DEFAULT_PREFIX
    connection_delay: float = 15.0
    _connected: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cached_skus = {}
        self.sku_to_product = {}
        self.product_to_sku = {}

    async def get_prefix(self, message: disnake.Message) -> list[str]:
        """Return the dynamic prefix list for message-based commands.

        This consults the centralized prefix system to resolve
        ``user > guild > default`` and then composes a prefix resolver that also
        supports ``@mention`` prefixes.

        Parameters
        ----------
        message : disnake.Message
            The incoming message, used to infer user/guild context.

        Returns
        -------
        list[str]
            A list of accepted prefixes for the given message.
        """
        prefixes = await get_effective_prefix(message, default=self.default_prefix)
        resolver = commands.when_mentioned_or(*prefixes)
        bot_for_prefix = cast("commands.BotBase", self)
        return resolver(bot_for_prefix, message)

    async def get_context(
        self,
        message: disnake.Message,
        *,
        cls: type[commands.Context[Any]] | None = None,
    ) -> SpookyContext:
        """Return :class:`SpookyContext` by default for message command execution.

        Parameters
        ----------
        message : disnake.Message
            The incoming message to build context for.
        cls : type[commands.Context[Any]] | None, optional
            Alternative context class. Defaults to :class:`SpookyContext`.

        Returns
        -------
        SpookyContext
            The resolved context instance.
        """
        context_cls: type[commands.Context[Any]] = cls or SpookyContext
        bot_base = cast("commands.BotBase", self)
        context = await commands.BotBase.get_context(bot_base, message, cls=context_cls)
        return cast(SpookyContext, context)

    async def connect(
        self, *, reconnect: bool = True, ignore_session_start_limit: bool = False
    ) -> None:
        """Delay connection slightly to reduce double-instance race conditions.

        Helpful during deployments to allow older instances to shut down cleanly
        before this process begins handling events.

        Parameters
        ----------
        reconnect : bool, optional
            Whether to reconnect on disconnect, by default ``True``.
        ignore_session_start_limit : bool, optional
            Forwarded to :meth:`disnake.Client.connect`, by default ``False``.

        Notes
        -----
        - After the delay and successful connection, ``self._connected`` is set to ``True``.
        """
        logger.info("Starting connection. Adding a delay of {} seconds...", self.connection_delay)
        await asyncio.sleep(self.connection_delay)
        logger.info("Delay completed. Proceeding with connection process.")
        await super().connect(
            reconnect=reconnect, ignore_session_start_limit=ignore_session_start_limit
        )
        self._connected = True

    def dispatch(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Dispatch events only when the bot is ready (except ``on_ready``).

        Parameters
        ----------
        event : str
            The event name (e.g., ``"on_message"``).
        *args, **kwargs : Any
            Arguments forwarded to the parent dispatch.

        Notes
        -----
        - Events other than ``on_ready`` are ignored until :meth:`is_ready` returns ``True``.
        """
        if event != "on_ready" and not self.is_ready():
            logger.debug("Bot not ready. Skipping event: {}", event)
            return
        return super().dispatch(event, *args, **kwargs)

    def find_extensions(
        self,
        root_module: str,
        *,
        package: str | None = None,
        ignore: abc.Iterable[str] | abc.Callable[[str], bool] | None = None,
    ) -> abc.Sequence[str]:
        """Return fully qualified module names for extensions under ``root_module``.

        Accepts file paths or module names and walks all sub-packages, applying an
        optional ignore filter.

        Parameters
        ----------
        root_module : str
            The root module name or filesystem path to a *package* (not a single file).
            Examples: ``"spooky.bot.extensions"`` or ``"./spooky/bot/extensions"``.
        package : str | None, optional
            Optional package name used with relative importing (as per
            :func:`importlib.import_module` semantics).
        ignore : Iterable[str] | Callable[[str], bool] | None, optional
            Either a collection of *prefixes* to ignore, or a callable receiving the
            module name and returning ``True`` when the module should be skipped.

        Returns
        -------
        Sequence[str]
            A tuple of dotted module names suitable for :meth:`load_extension`.

        Raises
        ------
        commands.ExtensionError
            If the root module cannot be found or is not a package.
        ValueError
            If a filesystem path escapes the current working directory.

        Notes
        -----
        - Path inputs are converted to dotted module names relative to the current
          working directory. Paths outside the cwd are not allowed.
        """
        if "/" in root_module or "\\" in root_module:
            path = os.path.relpath(root_module)
            if ".." in path:
                raise ValueError(
                    "Paths outside the cwd are not supported. "
                    "Use the importable module name instead."
                )
            root_module = path.replace(os.sep, ".")

        # Resolve the root module name using a custom error handling.
        root_module = self._resolve_name(root_module, package)

        if not (spec := importlib.util.find_spec(root_module)):
            raise commands.ExtensionError(
                f"Unable to find root module '{root_module}'", name=root_module
            )

        if not (paths := spec.submodule_search_locations):
            raise commands.ExtensionError(
                f"Module '{root_module}' is not a package", name=root_module
            )

        return tuple(_walk_modules(paths, prefix=f"{spec.name}.", ignore=ignore))

    def load_extensions(
        self,
        root_module: str,
        *,
        package: str | None = None,
        ignore: abc.Iterable[str] | abc.Callable[[str], bool] | None = None,
        load_callback: abc.Callable[[str], None] | None = None,
    ) -> None:
        """Load all extensions discovered under ``root_module``.

        Parameters
        ----------
        root_module : str
            The root module name or filesystem path to a package to discover under.
        package : str | None, optional
            Package name to assist in resolving the module (for relative imports).
        ignore : Iterable[str] | Callable[[str], bool] | None, optional
            Patterns (prefixes) or a callable to ignore certain modules.
        load_callback : Callable[[str], None] | None, optional
            Optional callback invoked for each successfully loaded extension.

        Notes
        -----
        - Errors during individual extension loading are **logged** and **skipped**;
          loading continues for the remaining modules.
        """
        for ext_name in self.find_extensions(root_module, package=package, ignore=ignore):
            try:
                self.load_extension(ext_name)
            except commands.ExtensionError as err:
                logger.error("Failed to load extension: {}", ext_name)
                logger.error("".join(format_exception(err)))
                continue

            if load_callback is not None:
                load_callback(ext_name)


def _walk_modules(
    paths: abc.Iterable[str],
    prefix: str = "",
    ignore: abc.Iterable[str] | abc.Callable[[str], bool] | None = None,
) -> abc.Iterator[str]:
    """Yield module names by walking the provided package paths.

    Parameters
    ----------
    paths : Iterable[str]
        Directory paths to search for modules.
    prefix : str, optional
        Prefix to prepend to discovered module names (e.g., ``"spooky.bot.extensions."``).
    ignore : Iterable[str] | Callable[[str], bool] | None, optional
        Patterns (treated as name prefixes) or a predicate called with the dotted
        module name; return ``True`` to skip a module.

    Returns
    -------
    Iterator[str]
        Iterator over fully-qualified module names.

    Raises
    ------
    TypeError
        If ``ignore`` is provided as a single string instead of an iterable or callable.

    Notes
    -----
    - If a package module has a top-level ``setup`` function (classic disnake/discord.py
      extension pattern), the package itself is yielded and its children are not required
      to be enumerated for that extension to load.
    """
    if isinstance(ignore, str):
        raise TypeError("`ignore` must be an iterable of strings or a callable")

    if isinstance(ignore, abc.Iterable):
        ignore_seq = cast(abc.Iterable[str], ignore)
        ignore_tup = tuple(ignore_seq)
        ignore = lambda path: path.startswith(ignore_tup)  # noqa: E731

    seen: set[str] = set()

    for _, name, ispkg in pkgutil.iter_modules(paths, prefix):
        if ignore and ignore(name):
            continue

        if not ispkg:
            yield name
            continue

        # For packages, import the module to check for a setup function.
        mod = importlib.import_module(name)

        # If the module has a 'setup' function, yield it immediately.
        if hasattr(mod, "setup"):
            yield name
            continue

        sub_paths: list[str] = []
        for p in mod.__path__ or []:  # type: ignore[attr-defined]
            if p not in seen:
                seen.add(p)
                sub_paths.append(p)

        if sub_paths:
            yield from _walk_modules(sub_paths, prefix=f"{name}.", ignore=ignore)
