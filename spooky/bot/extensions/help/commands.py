"""Cog exposing the message-based help command.

This module implements a lightweight, **prefix-based** help command that renders
the bot's command catalog using our v2 container UI.

Overview
--------
- The :class:`HelpCommands` cog registers a single prefixed command, ``help``.
- It computes the effective prefix for the current context, builds the help
  menu model via :func:`.utils.build_help_menu`, and renders it with
  :class:`.view.HelpView`.
- The resulting component payload is sent as a **container-only** message and the
  view is stored in Disnake's state so subsequent interactions resolve correctly.

Notes
-----
- This help is intended for **message commands**. For slash command discovery,
  rely on Discords native UI and command categories.
"""

from __future__ import annotations

from disnake.ext import commands
from spooky.bot import Spooky
from spooky.bot.context import SpookyContext
from spooky.bot.prefix import DEFAULT_PREFIX
from spooky.ext.components.command_gate import require_command_enabled

from .utils import build_help_menu, resolve_help_topic, resolve_prefix
from .view import HelpView

__all__ = ["HelpCommands"]


class HelpCommands(commands.Cog):
    """Expose the help command for prefixed invocations."""

    def __init__(self, bot: Spooky) -> None:
        """Initialize the cog with the running bot instance."""
        self.bot = bot

    @commands.command(
        name="help",
        extras={
            "category": "General",
            "example": ",help",
            "help_topics": ("help", "commands"),
        },
    )
    @require_command_enabled()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    async def help_message(self, ctx: SpookyContext, *, topic: str | None = None) -> None:
        """Display the bot's command catalog in chat.

        Parameters
        ----------
        topic : Optional help topic (category or command slug) used to focus the
            menu on the expected panel.
        """
        default_prefix = getattr(self.bot, "default_prefix", DEFAULT_PREFIX)
        prefix = resolve_prefix(getattr(ctx, "prefix", None), default_prefix)

        menu = build_help_menu(self.bot, prefix)
        initial_category: str | None = None
        initial_command: str | None = None
        focus_mode = False
        focus_commands: tuple[str, ...] | None = None
        if topic:
            resolved = resolve_help_topic(menu, topic)
            if resolved is not None:
                initial_category = resolved.category_key
                initial_command = resolved.command_key
                focus_commands = resolved.command_keys or None
                focus_mode = bool(initial_category or initial_command or focus_commands)

        view = HelpView(
            menu,
            user_id=ctx.author.id,
            initial_category=initial_category,
            initial_command=initial_command,
            focus_mode=focus_mode,
            focus_command_keys=focus_commands,
        )

        components = view.build_component_input()
        message = await ctx.send(components=components)

        # Persist the view so component interactions get routed to it.
        state = getattr(message, "_state", None)
        if state is not None:
            state.store_view(view, message.id)

        view.bind_to_message(message)
        await view.wait()
