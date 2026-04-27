"""Slash-command error handling and telemetry (Cog).

Centralizes error handling for application commands and provides:
- A friendly, ephemeral message to users when something goes wrong.
- Respect for command/cog-specific error handlers to avoid double-handling.
- Optional exception telemetry (traceback + context) to a configured channel
  via the ``SPOOKY_TELEMETRY_CHANNEL_ID`` environment variable.

This module is designed to fail soft: user notifications are best-effort and
telemetry errors are logged but never re-raised to disrupt command flow.
"""

from __future__ import annotations

import importlib
import os
import traceback
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from io import BytesIO
from typing import Any, cast

import disnake
from disnake import TextChannel
from disnake.ext import commands
from loguru import logger
from spooky.bot import Spooky
from spooky.core import messages
from spooky.core.exceptions import (
    MissingSubcommandError,
    SpookyUnhandledCommandError,
    UserMessageError,
)
from spooky.db.errors import is_db_capacity_error
from spooky.ext.components.v2.card import status_card


def _common_error_message() -> str:
    """Return a generic, user-facing error message.

    Returns
    -------
    str
        Localized or centralized generic error copy suitable for display
        in an ephemeral response.
    """
    return messages.exceptions.common


async def _respond_ephemeral(
    inter: disnake.CommandInteraction[Spooky], *, description: str
) -> None:
    """Reply (or follow up) with an ephemeral error embed.

    Attempts to use ``interaction.response`` if available; otherwise falls back
    to a follow-up. Any delivery failure (timeouts, unknown interaction, etc.)
    is intentionally swallowed.

    Parameters
    ----------
    inter
        The interaction to respond to.
    description
        The error text to include in the embed.
    """
    embed = status_card(False, description)
    try:
        if inter.response.is_done():
            await inter.followup.send(embed=embed, ephemeral=True)
        else:
            await inter.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        # If we can't notify the user (timeout/unknown interaction), just swallow here.
        pass


async def _resolve_telemetry_channel(bot: Spooky) -> TextChannel | None:
    """Return the configured telemetry channel, if available."""
    chan_id_str = os.getenv("SPOOKY_TELEMETRY_CHANNEL_ID")
    chan_id: int | None = int(chan_id_str) if chan_id_str and chan_id_str.isdigit() else None
    if not chan_id:
        return None

    try:
        models_mod = importlib.import_module("spooky.models")
        channel = await models_mod.ensure_channel(bot, chan_id)
    except Exception as exc:
        logger.error(f"Failed to resolve telemetry channel: {exc}")
        return None

    if channel is None:
        logger.error(f"Telemetry channel not found or inaccessible: {chan_id}")
        return None
    if not isinstance(channel, TextChannel):
        logger.error(f"Telemetry channel {chan_id} is not a TextChannel")
        return None

    return channel


def _format_slash_command_name(inter: disnake.CommandInteraction[Spooky]) -> str:
    """Return a display-friendly slash command reference for telemetry."""
    try:
        if inter.application_command:
            return f"</{inter.application_command.qualified_name}:{inter.application_id}>"
    except Exception:
        pass
    return "<unknown>"


def _format_prefix_command_name(ctx: commands.Context[Any]) -> str:
    """Return the invoked prefix command name for telemetry."""
    command = getattr(ctx, "command", None)
    if command is None:
        invoked_with = getattr(ctx, "invoked_with", None)
        return str(invoked_with) if invoked_with else "<unknown>"

    prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", "") or ""
    qualified = command.qualified_name
    signature = getattr(command, "signature", "")
    if signature:
        return f"{prefix}{qualified} {signature}".strip()
    return f"{prefix}{qualified}".strip()


async def _send_command_telemetry(
    *,
    bot: Spooky,
    error: BaseException,
    guild: disnake.Guild | None,
    user: disnake.abc.User,
    command_name: str,
) -> None:
    """Send an exception report with traceback to the telemetry channel, if configured."""
    telemetry_channel = await _resolve_telemetry_channel(bot)
    if telemetry_channel is None:
        return

    trace = "".join(traceback.format_exception(error))
    guild_name = getattr(guild, "name", None) or "<NO GUILD>"

    desc = (
        "**Error Context**\n"
        f"Guild: `{guild_name}`\n"
        f"User: <@{user.id}> (@{getattr(user, 'name', user)})\n"
        f"Command: {command_name}\n"
        "See the attached traceback for details."
    )

    embed = status_card(False, desc)
    exc_name = type(error).__name__
    exc_msg = str(error) or "<no message>"
    embed.add_field(name="Exception", value=f"{exc_name}: {exc_msg}"[:1024], inline=False)

    try:
        await telemetry_channel.send(
            embed=embed,
            file=disnake.File(BytesIO(trace.encode("utf-8")), filename="Traceback.txt"),
        )
    except Exception as send_err:
        logger.error(f"Failed to send telemetry: {send_err}")


def _map_error_to_user_message(error: BaseException, *, usage: str | None = None) -> str | None:
    """Return a friendly user-facing message for known error types."""
    if is_db_capacity_error(error):
        return messages.errors.generic.format(
            message="Database is currently at capacity. Please try again in a moment."
        )
    if isinstance(
        error, (UserMessageError, commands.MissingPermissions, commands.BotMissingPermissions)
    ):
        return messages.errors.generic.format(message=str(error))
    if isinstance(error, commands.NotOwner):
        return messages.errors.owner_only
    if isinstance(error, commands.DisabledCommand):
        return messages.errors.disabled_command
    if isinstance(error, commands.NoPrivateMessage):
        return messages.errors.no_private_message
    if isinstance(error, getattr(commands, "NSFWChannelRequired", ())):
        return messages.errors.nsfw_required
    if isinstance(error, commands.CommandOnCooldown):
        return messages.errors.cooldown.format(
            seconds=f"{error.retry_after:.2f}", bucket=error.type.name
        )
    if isinstance(error, commands.MaxConcurrencyReached):
        return messages.errors.max_concurrency.format(number=error.number, scope=error.per.name)
    if isinstance(error, (commands.MissingRequiredArgument, MissingSubcommandError)) and usage:
        return messages.errors.missing_required_argument.format(usage=usage)
    if isinstance(error, (commands.UserInputError, commands.CheckFailure)):
        return messages.errors.generic.format(message=str(error))
    if isinstance(error, disnake.Forbidden):
        return messages.errors.forbidden
    if isinstance(error, disnake.HTTPException):
        return messages.errors.http_exception
    return None


def _format_prefix_usage(
    ctx: commands.Context[Any], *, include_group_subcommands: bool = False
) -> str:
    """Return a usage string for the current prefix command."""
    prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", "") or ""
    command = getattr(ctx, "command", None)
    if not command:
        return prefix.strip()

    usage_parts: list[str] = [f"{prefix}{command.qualified_name}".strip()]
    signature = getattr(command, "signature", "")
    if signature and not (include_group_subcommands and isinstance(command, commands.GroupMixin)):
        usage_parts.append(signature)

    if include_group_subcommands and isinstance(command, commands.GroupMixin):
        subcommands: list[str] = []
        raw_subcommands = cast(Iterable[Any], getattr(cast(Any, command), "commands", ()))
        for sub in raw_subcommands:
            if getattr(sub, "hidden", False):
                continue
            name = getattr(sub, "name", None)
            if not name:
                continue
            names = [str(name)]
            aliases = getattr(sub, "aliases", ()) or ()
            names.extend(str(alias) for alias in aliases if alias)
            deduped = " / ".join(dict.fromkeys(names))
            if deduped:
                subcommands.append(deduped)
        if subcommands:
            usage_parts.append(f"<{' | '.join(subcommands)}>")
    return " ".join(part for part in usage_parts if part).strip()


async def _respond_prefix_error(ctx: commands.Context[Any], *, description: str) -> None:
    """Send an error response for prefix commands, swallowing delivery failures."""
    error_sender = getattr(ctx, "error", None)
    if callable(error_sender):
        sender = cast(Callable[..., Awaitable[Any]], error_sender)
        with suppress(Exception):
            await sender(description, ensure_period=False)
        return

    embed = status_card(False, description)
    with suppress(Exception):
        await ctx.send(embed=embed)


class ErrorHandler(commands.Cog):
    """Global command error handler for slash and prefix invocations.

    This cog attaches top-level listeners for ``on_slash_command_error`` and
    ``on_command_error`` that:
    - Skip handling when per-command/cog handlers are present.
    - Classify common error types into user-friendly messages (including usage
      hints for missing prefix arguments).
    - Log unknown exceptions, wrap them for central logging compatibility, and
      ship telemetry (if configured).
    """

    def __init__(self, bot: Spooky) -> None:
        """Initialize the cog.

        Parameters
        ----------
        bot
            The running :class:`~spooky.bot.Spooky` instance.
        """
        self.bot = bot

    @commands.Cog.listener()
    async def on_slash_command_error(
        self, inter: disnake.CommandInteraction[Spooky], error: commands.CommandError
    ) -> None:
        """Top-level slash command error handler.

        Behavior
        --------
        - If a permission/helper already sent an error (``_spooky_error_sent``),
          do nothing.
        - If the command or its cog defines its own error handler, do nothing.
        - Otherwise, map the error to a user-facing message when possible,
          log unknown exceptions, wrap with :class:`SpookyUnhandledCommandError`
          for central pipelines, optionally send telemetry, and finally send a
          best-effort ephemeral response to the user.

        Parameters
        ----------
        inter
            The command interaction that raised an error.
        error
            The command error captured by the dispatcher.
        """
        # If a permission helper already sent an ephemeral response, skip user-facing output.
        if getattr(inter, "_spooky_error_sent", False):
            return

        # Respect per-command/cog error handlers
        if (command := inter.application_command) and command.has_error_handler():
            return
        with suppress(Exception):
            cog = getattr(command, "cog", None)
            if cog and getattr(cog, "has_slash_error_handler", lambda: False)():
                return

        actual_error = getattr(error, "original", error)

        user_text = _map_error_to_user_message(actual_error)

        if user_text is None:
            logger.exception(actual_error)
            # Normalize for any central logging that expects this wrapper
            _ = SpookyUnhandledCommandError(original=actual_error)
            user_text = _common_error_message()
            await _send_command_telemetry(
                bot=self.bot,
                error=actual_error,
                guild=inter.guild,
                user=inter.user,
                command_name=_format_slash_command_name(inter),
            )

        await _respond_ephemeral(inter, description=user_text)

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context[Any], error: commands.CommandError
    ) -> None:
        """Top-level prefix command error handler."""
        if isinstance(error, commands.CommandNotFound):
            return

        command = getattr(ctx, "command", None)
        if command and command.has_error_handler():
            return

        cog = getattr(ctx, "cog", None)
        if cog:
            cog_command_error = getattr(cog, "cog_command_error", None)
            if cog_command_error and commands.Cog._get_overridden_method(cog_command_error):
                return

        actual_error = getattr(error, "original", error)

        usage_hint: str | None = None
        if isinstance(actual_error, commands.MissingRequiredArgument):
            usage_hint = _format_prefix_usage(ctx)
        elif isinstance(actual_error, MissingSubcommandError):
            usage_hint = _format_prefix_usage(ctx, include_group_subcommands=True)

        user_text = _map_error_to_user_message(actual_error, usage=usage_hint)

        if user_text is None:
            logger.exception(actual_error)
            # Normalize for any central logging that expects this wrapper
            _ = SpookyUnhandledCommandError(original=actual_error)
            user_text = _common_error_message()
            await _send_command_telemetry(
                bot=self.bot,
                error=actual_error,
                guild=getattr(ctx, "guild", None),
                user=ctx.author,
                command_name=_format_prefix_command_name(ctx),
            )

        await _respond_prefix_error(ctx, description=user_text)
