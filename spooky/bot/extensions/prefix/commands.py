"""Message commands for managing prefix overrides.

This cog exposes a small set of **message-based** commands for reading and
modifying prefix overrides at the *user* and *guild* scope.

Overview
--------
- ``,prefix user [prefix]`` — Set or clear your personal prefix.
- ``,prefix guild [prefix]`` — Set or clear this guild's prefix (requires Manage Guild).
- ``,prefix status`` — Show the default, user, and guild prefixes.

Design notes
------------
- Input validation and normalization are delegated to
  :func:`sanitize_override`, which enforces the same constraints used by the
  global prefix layer (:mod:`spooky.bot.prefix`).
- After each successful write, the in-process/Redis prefix snapshot is refreshed
  via :func:`refresh_user_prefix` / :func:`refresh_guild_prefix` to ensure
  immediate consistency for subsequent invocations.
- Permission checks for guild-wide changes use the same override-aware helper
  used elsewhere in the codebase (:func:`has_perms_or_override`).

Typical usage
-------------
Users can manage prefixes purely through message commands:

- Clear personal prefix (back to default)::

    ,prefix user

- Set personal prefix to ``!``::

    ,prefix user !

- Set guild prefix to ``;`` (requires Manage Guild)::

    ,prefix guild ;

- Inspect prefix overrides in context::

    ,prefix status
"""

from __future__ import annotations

import disnake
from disnake.ext import commands
from spooky.bot import Spooky
from spooky.bot.context import SpookyContext
from spooky.bot.prefix import DEFAULT_PREFIX, refresh_guild_prefix, refresh_user_prefix
from spooky.core.checks import fakeperms_or_discordperm
from spooky.core.exceptions import MissingSubcommandError
from spooky.db import get_session
from spooky.ext.constants import FREE_CONFIGS_CHANNEL_ID
from spooky.models.entities.permissions import AppPermission

from .utils import (
    build_status_embed,
    ensure_guild,
    ensure_user,
    fetch_guild_prefix,
    fetch_user_prefix,
    sanitize_override,
)

__all__ = ["PrefixCommands"]


class PrefixCommands(commands.Cog):
    """Commands for managing bot prefixes.

    This cog groups message-based prefix operations behind a single ``prefix``
    command group. The handlers are intentionally lightweight: they validate
    input, perform a small transactional update, and refresh the prefix cache.

    Parameters
    ----------
    bot : Spooky
        Running bot instance, retained for default prefix resolution and
        permission checks.
    """

    def __init__(self, bot: Spooky) -> None:
        self.bot = bot

    @commands.group(
        name="prefix",
        invoke_without_command=True,
        hidden=True,
        extras={
            "category": "Configuration",
            "example": ",prefix",
            "help_topics": ("prefix", "prefix commands"),
        },
    )
    async def prefix_group(self, ctx: SpookyContext) -> None:
        """Handle invocations of the base prefix command.

        Parameters
        ----------
        ctx : SpookyContext
            The invocation context.
        """
        command = getattr(ctx, "command", None)
        qualified_name = getattr(command, "qualified_name", None) or "prefix"
        raise MissingSubcommandError(qualified_name)

    @prefix_group.command(
        name="user", extras={"category": "Configuration", "example": ",prefix user !"}
    )
    async def prefix_user(self, ctx: SpookyContext, prefix: str | None = None) -> None:
        """Manage the invoking user's custom prefix.

        Parameters
        ----------
        prefix : The new prefix to apply (length ≤ 2). Omit or pass an
            empty/whitespace-only value to **clear** your override and fall back
            to the default.
        """
        default_prefix = getattr(self.bot, "default_prefix", DEFAULT_PREFIX)

        try:
            sanitized = sanitize_override(
                prefix,
                default=default_prefix,
                allow_default=True,
            )
        except ValueError as exc:
            await ctx.error(str(exc))
            return

        async with get_session() as session:
            user = await ensure_user(session, ctx.author.id)
            current = user.prefix
            if sanitized == current:
                if sanitized is None:
                    await ctx.warning("You do not have a custom prefix configured.")
                else:
                    await ctx.warning(f"Your prefix is already `{sanitized}`.")
                return

            user.prefix = sanitized
            await session.flush()

        await refresh_user_prefix(ctx.author.id, default=default_prefix)

        if sanitized is None:
            guild_prefix: str | None = None
            if ctx.guild is not None:
                guild_prefix = await fetch_guild_prefix(ctx.guild.id)

            if guild_prefix is not None:
                await ctx.approve(f"Now in use: `{guild_prefix}`.")
            else:
                await ctx.approve(f"Prefix reset to `{default_prefix}`.")
        else:
            await ctx.approve(f"Prefix set to `{sanitized}`.")

    @prefix_group.command(
        name="guild",
        extras={
            "category": "Configuration",
            "example": ",prefix guild ;",
        },
    )
    @fakeperms_or_discordperm(AppPermission.MANAGE_GUILD)
    async def prefix_guild(self, ctx: SpookyContext, prefix: str | None = None) -> None:
        """Manage the current guild's custom prefix.

        Parameters
        ----------
        prefix : The new prefix to apply (length ≤ 2). Omit or pass an
            empty/whitespace-only value to **clear** the guild override.


        """
        guild = ctx.guild
        if guild is None:
            await ctx.error("This command can only be used inside a guild.")
            return

        default_prefix = getattr(self.bot, "default_prefix", DEFAULT_PREFIX)
        try:
            sanitized = sanitize_override(prefix, default=default_prefix)
        except ValueError as exc:
            await ctx.error(str(exc))
            return

        async with get_session() as session:
            guild_record = await ensure_guild(session, guild.id)
            current = guild_record.prefix
            if sanitized == current:
                if sanitized is None:
                    await ctx.warning("This guild already uses the default prefix.")
                else:
                    await ctx.warning(f"The guild prefix is already `{sanitized}`.")
                return

            guild_record.prefix = sanitized
            await session.flush()

        await refresh_guild_prefix(guild.id, default=default_prefix)

        if sanitized is None:
            await ctx.approve(f"Prefix reset to `{default_prefix}`.")
        else:
            await ctx.approve(f"Prefix set to `{sanitized}`.")

    @prefix_group.command(
        name="status", extras={"category": "Configuration", "example": ",prefix status"}
    )
    async def prefix_status(self, ctx: SpookyContext) -> None:
        """Display prefix information for the current context."""
        default_prefix = getattr(self.bot, "default_prefix", DEFAULT_PREFIX)

        user_prefix = await fetch_user_prefix(ctx.author.id)

        guild_prefix: str | None = None
        guild_name = "Direct Message"
        if ctx.guild is not None:
            guild_name = ctx.guild.name
            guild_prefix = await fetch_guild_prefix(ctx.guild.id)

        embed = build_status_embed(
            default_prefix=default_prefix,
            user_prefix=user_prefix,
            guild_prefix=guild_prefix,
            guild_name=guild_name,
        )

        await ctx.send(embed=embed)

    @commands.command(
        name="subscriber",
        aliases=("sb", "sc", "sr"),
        hidden=True,
        extras={
            "category": "Moderation",
            "example": ",subscriber @member",
            "help_topics": ("subscriber",),
        },
    )
    @fakeperms_or_discordperm(AppPermission.MANAGE_ROLES)
    async def subscriber(self, ctx: SpookyContext, member: disnake.Member | None = None) -> None:
        """Grant the configured subscriber role to a mentioned guild member."""
        if member is None:
            prefix = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", "") or ""
            usage = f"{prefix}subscriber @member".strip()
            await ctx.error(
                f"Missing required argument `member`.\nUsage: `{usage}`",
                ensure_period=False,
            )
            return

        guild = ctx.guild
        if guild is None:
            await ctx.error("This command can only be used inside a guild.")
            return

        subscriber_role_id = 1495576579105886348
        role = guild.get_role(subscriber_role_id)
        if role is None:
            await ctx.error(f"Subscriber role `{subscriber_role_id}` was not found in this server.")
            return

        if role in member.roles:
            await ctx.warning(f"{member.mention} already has {role.mention}.")
            return

        await member.add_roles(
            role,
            reason=f"Granted by {ctx.author} via prefix subscriber command.",
        )
        await ctx.approve(
            "🎉 "
            f"Welcome, {member.mention}! You now have access to the free configs. "
            f"You can find them in <#{FREE_CONFIGS_CHANNEL_ID}>."
        )
