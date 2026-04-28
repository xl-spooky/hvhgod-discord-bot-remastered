"""Prefix command error handling for private runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from typing import Any, cast

from disnake.ext import commands
from spooky.bot import Spooky
from spooky.core.exceptions import MissingSubcommandError
from spooky.ext.components.v2.card import status_card

__all__ = ["ErrorHandler"]


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


async def _send_prefix_error(ctx: commands.Context[Any], *, description: str) -> None:
    """Send an error response for prefix commands, swallowing delivery failures."""
    error_sender = getattr(ctx, "error", None)
    if callable(error_sender):
        sender = cast(Callable[..., Awaitable[Any]], error_sender)
        with suppress(Exception):
            await sender(description, ensure_period=False)
        return

    embed = status_card(False, description, ensure_period=False)
    with suppress(Exception):
        await ctx.send(embed=embed)


class ErrorHandler(commands.Cog):
    """Handle common prefix command errors with user-friendly messages."""

    def __init__(self, bot: Spooky) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(
        self,
        ctx: commands.Context[Any],
        error: commands.CommandError,
    ) -> None:
        """Handle command-not-found and missing-subcommand errors."""
        original = getattr(error, "original", error)

        if isinstance(original, commands.CommandNotFound):
            prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", ",") or ","
            await _send_prefix_error(
                ctx,
                description=(
                    "Command not found. "
                    f"Try `{prefix}prefix status` or `{prefix}help` if available."
                ),
            )
            return

        if isinstance(original, MissingSubcommandError):
            usage = _format_prefix_usage(ctx, include_group_subcommands=True)
            await _send_prefix_error(ctx, description=f"Usage: `{usage}`")
            return

        if isinstance(original, commands.MissingRequiredArgument):
            usage = _format_prefix_usage(ctx)
            parameter_name = getattr(getattr(original, "param", None), "name", "argument")
            await _send_prefix_error(
                ctx,
                description=(f"Missing required argument `{parameter_name}`.\nUsage: `{usage}`"),
            )
            return
