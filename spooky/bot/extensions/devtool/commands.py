"""Slash commands for developer-only maintenance utilities."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Literal

import disnake
from disnake.ext import commands
from spooky.bot import Spooky
from spooky.core.checks import fakeperms_or_discordperm
from spooky.db import get_session
from spooky.ext.components.v2.card import status_card
from spooky.ext.constants import (
    DEFAULT_BUYER_CATEGORY_ID,
    OWNER_ID,
    REQUIRED_BUYER_ROLE_ID,
    SEMI_LEGIT_MAIN_ROLE_ID,
    SEMI_LEGIT_VISUAL_ROLE_ID,
    SEMI_RAGE_MAIN_ROLE_ID,
    SEMI_RAGE_VISUAL_ROLE_ID,
    STATS_BOOSTER_ROLE_ID,
    VAC_TIPS_CHANNEL_ID,
)
from spooky.ext.message import render_boosting_services_message, render_buyer_welcome
from spooky.models.entities.buyers import BuyerChannel, BuyerCode
from spooky.models.entities.join_pings import JoinPingConfig
from spooky.models.entities.permissions import AppPermission, UserPermissionOverride
from sqlalchemy import delete, select
from thefuzz import process

from .helpers import build_member_code_summary, group_codes_by_product_and_role

PermissionAction = Literal["Add", "Remove"]
CodeBundleOption = Literal["Semi-Legit", "Semi-Rage", "Stats-Booster"]
CodeBranchOption = Literal["Main Branch", "Visual"]
CodeColorOption = Literal["Pink", "Purple", "Yellow", "Blue", "Red", "Green", "Black & White"]
CodeProductOption = Literal["memesense", "fatality"]
FUZZY_PERMISSION_SCORE_THRESHOLD = 65
MAX_PERMISSION_CHOICES = 25

__all__ = ["DevtoolCommands"]


class DevtoolCommands(commands.Cog):
    """Developer tooling command group.

    This cog exposes restricted slash commands for maintaining fake-permission
    overrides used by private deployments.
    """

    def __init__(self, bot: Spooky) -> None:
        self.bot = bot

    @commands.slash_command(
        name="devtool",
        default_member_permissions=disnake.Permissions(administrator=True),
        extras={
            "category": "Developer",
            "example": "/devtool permission action:Add user:@User permission:manage_guild",
            "help_topics": ("devtool", "permissions"),
        },
    )
    @fakeperms_or_discordperm(AppPermission.ADMINISTRATOR)
    async def devtool(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Root command group for developer tooling."""
        del inter

    @devtool.sub_command(name="permission")
    async def devtool_permission(
        self,
        inter: disnake.AppCmdInter[Spooky],
        action: PermissionAction,
        user: disnake.Member,
        permission: str,
    ) -> None:
        """Add or remove fake-permission overrides for a guild member.

        Parameters
        ----------
        action : Literal["Add", "Remove"]
            Whether to add or remove the selected permission override.
        user : disnake.Member
            Guild member whose fake permission will be edited.
        permission : str
            Permission name. Fuzzy matching is applied against the full
            :class:`AppPermission` catalog.
        """
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        if inter.guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        resolved_perm = self._resolve_permission_name(permission)
        if resolved_perm is None:
            await inter.response.send_message(
                embed=status_card(False, "Unable to match that permission name."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            if action == "Add":
                result = await session.execute(
                    select(UserPermissionOverride).where(
                        UserPermissionOverride.guild_id == int(inter.guild.id),
                        UserPermissionOverride.user_id == int(user.id),
                        UserPermissionOverride.perm_name == resolved_perm,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    row = UserPermissionOverride(
                        guild_id=int(inter.guild.id),
                        user_id=int(user.id),
                        perm_name=resolved_perm,
                        allowed=True,
                    )
                    session.add(row)
                else:
                    row.allowed = True
                message = f"Granted fake permission `{resolved_perm}` to {user.mention}"
            else:
                await session.execute(
                    delete(UserPermissionOverride).where(
                        UserPermissionOverride.guild_id == int(inter.guild.id),
                        UserPermissionOverride.user_id == int(user.id),
                        UserPermissionOverride.perm_name == resolved_perm,
                    )
                )
                message = f"Removed fake permission `{resolved_perm}` from {user.mention}"

        await inter.response.send_message(embed=status_card(True, message), ephemeral=True)

    @devtool.sub_command_group(name="buyer")
    async def devtool_buyer(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Subcommands for buyer forum lifecycle management."""
        del inter

    @devtool_buyer.sub_command(name="create")
    async def devtool_buyer_create(
        self,
        inter: disnake.AppCmdInter[Spooky],
        member: disnake.Member,
        category: disnake.CategoryChannel | None = None,
    ) -> None:
        """Create a private buyer forum visible only to the selected member.

        Parameters
        ----------
        member : disnake.Member
            Member who should have access to the created buyer forum.
        category : disnake.CategoryChannel | None, optional
            Optional category override. Defaults to ``DEFAULT_BUYER_CATEGORY_ID``.
        """
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        if not any(role.id == REQUIRED_BUYER_ROLE_ID for role in member.roles):
            await inter.response.send_message(
                embed=status_card(False, f"{member.mention} is missing the required buyer role."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(BuyerChannel.id).where(BuyerChannel.user_id == int(member.id)).limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                await inter.response.send_message(
                    embed=status_card(False, f"{member.mention} already has a buyer channel."),
                    ephemeral=True,
                )
                return

        await inter.response.defer(ephemeral=True)

        everyone_overwrite = disnake.PermissionOverwrite(view_channel=False)
        member_overwrite = self._buyer_member_overwrite()
        target_category = category
        if target_category is None:
            resolved = guild.get_channel(DEFAULT_BUYER_CATEGORY_ID)
            target_category = resolved if isinstance(resolved, disnake.CategoryChannel) else None

        forum_name = f"buyer-{member.display_name}".lower().replace(" ", "-")
        forum = await guild.create_forum_channel(
            name=forum_name[:100],
            category=target_category,
            overwrites={
                guild.default_role: everyone_overwrite,
                member: member_overwrite,
            },
            reason=f"Buyer forum requested by {inter.author} for {member}",
        )

        vac_tips_channel = f"<#{VAC_TIPS_CHANNEL_ID}>"
        welcome_message = render_buyer_welcome(
            user_mention=member.mention,
            vac_tips_channel_mention=vac_tips_channel,
        )

        intro_result = await forum.create_thread(name="INTRODUCTION", content=welcome_message)
        intro_thread = self._extract_created_thread(intro_result)
        contact_result = await forum.create_thread(
            name="CONTACT US",
            content=(
                f"{member.mention}\n"
                "Use this thread anytime if you need direct help, "
                "have account questions, or need support."
            ),
        )
        contact_thread = self._extract_created_thread(contact_result)
        boosting_result = await forum.create_thread(
            name="BOOSTING SERVICES",
            content=render_boosting_services_message(),
        )
        boosting_thread = self._extract_created_thread(boosting_result)
        config_thread_result = await forum.create_thread(
            name="CONFIG CODES",
            content="Config codes for this buyer will be posted in this thread.",
        )
        config_thread = self._extract_created_thread(config_thread_result)
        if (
            intro_thread is None
            or contact_thread is None
            or boosting_thread is None
            or config_thread is None
        ):
            await inter.followup.send(
                embed=status_card(
                    False,
                    "Failed to resolve created buyer threads for persistence.",
                ),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            session.add(
                BuyerChannel(
                    user_id=int(member.id),
                    channels={
                        "forum": int(forum.id),
                        "introduction_thread": int(intro_thread.id),
                        "contact_thread": int(contact_thread.id),
                        "boosting_services_thread": int(boosting_thread.id),
                        "config_codes_thread": int(config_thread.id),
                    },
                )
            )
            await session.flush()

        await inter.followup.send(
            embed=status_card(
                True,
                f"Created buyer forum {forum.mention} for {member.mention}",
            ),
            ephemeral=True,
        )

    @devtool_buyer.sub_command(name="remove")
    async def devtool_buyer_remove(
        self,
        inter: disnake.AppCmdInter[Spooky],
        member: disnake.Member | None = None,
        channel_id: str | None = None,
    ) -> None:
        """Delete a buyer forum and DB rows by member and/or channel lookup."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        if member is None and (channel_id is None or not channel_id.strip()):
            await inter.response.send_message(
                embed=status_card(False, "Provide at least one lookup: member or channel_id."),
                ephemeral=True,
            )
            return
        parsed_channel_id: int | None = None
        if channel_id is not None and channel_id.strip():
            raw = channel_id.strip()
            if not raw.isdigit():
                await inter.response.send_message(
                    embed=status_card(False, "channel_id must be a valid numeric snowflake."),
                    ephemeral=True,
                )
                return
            parsed_channel_id = int(raw)
        await inter.response.defer(ephemeral=True)

        async with get_session() as session:
            rows = (await session.execute(select(BuyerChannel))).scalars().all()
            if member is not None:
                rows = [row for row in rows if int(row.user_id) == int(member.id)]
            if parsed_channel_id is not None:
                rows = [
                    row
                    for row in rows
                    if parsed_channel_id in {int(value) for value in row.channels.values()}
                ]

            if not rows:
                await inter.followup.send(
                    embed=status_card(False, "No buyer record matched the provided lookup."),
                    ephemeral=True,
                )
                return

            deleted_channels = 0
            for row in rows:
                for saved_channel_id in {int(value) for value in row.channels.values()}:
                    channel = self.bot.get_channel(saved_channel_id)
                    if channel is None:
                        with suppress(Exception):
                            channel = await self.bot.fetch_channel(saved_channel_id)
                    if not isinstance(channel, disnake.abc.GuildChannel | disnake.Thread):
                        continue
                    with suppress(Exception):
                        await channel.delete(reason=f"buyer remove requested by {inter.author}")
                        deleted_channels += 1

            row_ids = [row.id for row in rows]
            await session.execute(delete(BuyerChannel).where(BuyerChannel.id.in_(row_ids)))
            await session.flush()

        await inter.followup.send(
            embed=status_card(
                True,
                (
                    f"Removed buyer record(s): {len(rows)}. "
                    f"Deleted channels/threads: {deleted_channels}"
                ),
            ),
            ephemeral=True,
        )

    @devtool_buyer.sub_command(name="bulkcreate")
    async def devtool_buyer_bulkcreate(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Temporarily create buyer forums/threads for buyer-role members missing records."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        buyers = [
            member
            for member in guild.members
            if any(role.id == REQUIRED_BUYER_ROLE_ID for role in member.roles)
        ]
        if not buyers:
            await inter.edit_original_response(
                embed=status_card(False, "No members with the required buyer role were found."),
            )
            return

        target_category = guild.get_channel(DEFAULT_BUYER_CATEGORY_ID)
        if not isinstance(target_category, disnake.CategoryChannel):
            target_category = None

        created = 0
        skipped = 0
        failed = 0
        for member in buyers:
            async with get_session() as session:
                existing = (
                    await session.execute(
                        select(BuyerChannel.id)
                        .where(BuyerChannel.user_id == int(member.id))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    skipped += 1
                    continue

            try:
                everyone_overwrite = disnake.PermissionOverwrite(view_channel=False)
                member_overwrite = self._buyer_member_overwrite()
                forum_name = f"buyer-{member.display_name}".lower().replace(" ", "-")
                forum = await guild.create_forum_channel(
                    name=forum_name[:100],
                    category=target_category,
                    overwrites={
                        guild.default_role: everyone_overwrite,
                        member: member_overwrite,
                    },
                    reason=f"Temporary bulk buyer forum creation by {inter.author}",
                )
                await asyncio.sleep(3)

                vac_tips_channel = f"<#{VAC_TIPS_CHANNEL_ID}>"
                welcome_message = render_buyer_welcome(
                    user_mention=member.mention,
                    vac_tips_channel_mention=vac_tips_channel,
                )

                intro_result = await forum.create_thread(
                    name="INTRODUCTION", content=welcome_message
                )
                await asyncio.sleep(3)
                contact_result = await forum.create_thread(
                    name="CONTACT US",
                    content=(
                        f"{member.mention}\n"
                        "Use this thread anytime if you need direct help, "
                        "have account questions, or need support."
                    ),
                )
                await asyncio.sleep(3)
                boosting_result = await forum.create_thread(
                    name="BOOSTING SERVICES",
                    content=render_boosting_services_message(),
                )
                await asyncio.sleep(3)
                config_thread_result = await forum.create_thread(
                    name="CONFIG CODES",
                    content="Config codes for this buyer will be posted in this thread.",
                )

                intro_thread = self._extract_created_thread(intro_result)
                contact_thread = self._extract_created_thread(contact_result)
                boosting_thread = self._extract_created_thread(boosting_result)
                config_thread = self._extract_created_thread(config_thread_result)
                if (
                    intro_thread is None
                    or contact_thread is None
                    or boosting_thread is None
                    or config_thread is None
                ):
                    failed += 1
                    continue

                async with get_session() as session:
                    session.add(
                        BuyerChannel(
                            user_id=int(member.id),
                            channels={
                                "forum": int(forum.id),
                                "introduction_thread": int(intro_thread.id),
                                "contact_thread": int(contact_thread.id),
                                "boosting_services_thread": int(boosting_thread.id),
                                "config_codes_thread": int(config_thread.id),
                            },
                        )
                    )
                    await session.flush()
                created += 1
                await asyncio.sleep(3)
            except Exception:
                failed += 1

        await inter.edit_original_response(
            embed=status_card(
                True,
                (
                    f"Temporary bulk create complete. Created: {created}. "
                    f"Skipped existing: {skipped}. Failed: {failed}."
                ),
            ),
        )

    @devtool.sub_command_group(name="ping")
    async def devtool_ping(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Subcommands for temporary member join ping configuration."""
        del inter

    @devtool_ping.sub_command(name="create")
    async def devtool_createping(
        self,
        inter: disnake.AppCmdInter[Spooky],
        channel: disnake.abc.GuildChannel | disnake.Thread,
    ) -> None:
        """Register a channel/thread for temporary member join pings."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(JoinPingConfig.id).where(
                        JoinPingConfig.guild_id == int(guild.id),
                        JoinPingConfig.channel_id == int(channel.id),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                await inter.response.send_message(
                    embed=status_card(
                        False, f"{channel.mention} is already configured for join pings."
                    ),
                    ephemeral=True,
                )
                return

            session.add(JoinPingConfig(guild_id=int(guild.id), channel_id=int(channel.id)))
            await session.flush()

        await inter.response.send_message(
            embed=status_card(True, f"Enabled temporary join pings in {channel.mention}."),
            ephemeral=True,
        )

    @devtool_ping.sub_command(name="delete")
    async def devtool_deleteping(
        self,
        inter: disnake.AppCmdInter[Spooky],
        channel: disnake.abc.GuildChannel | disnake.Thread,
    ) -> None:
        """Remove a channel/thread from temporary member join pings."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(JoinPingConfig.id).where(
                        JoinPingConfig.guild_id == int(guild.id),
                        JoinPingConfig.channel_id == int(channel.id),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                await inter.response.send_message(
                    embed=status_card(
                        False, f"{channel.mention} was not configured for join pings."
                    ),
                    ephemeral=True,
                )
                return

            await session.execute(
                delete(JoinPingConfig).where(
                    JoinPingConfig.guild_id == int(guild.id),
                    JoinPingConfig.channel_id == int(channel.id),
                )
            )
            await session.flush()

        await inter.response.send_message(
            embed=status_card(True, f"Disabled temporary join pings in {channel.mention}."),
            ephemeral=True,
        )

    @devtool_ping.sub_command(name="status")
    async def devtool_pingstatus(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Show configured channels that receive temporary join pings."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        select(JoinPingConfig.channel_id).where(
                            JoinPingConfig.guild_id == int(guild.id)
                        )
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            await inter.response.send_message(
                embed=status_card(False, "No join ping channels configured for this guild."),
                ephemeral=True,
            )
            return

        mentions = "\n".join(f"- <#{int(channel_id)}> (`{int(channel_id)}`)" for channel_id in rows)
        await inter.response.send_message(
            embed=status_card(True, f"Join ping channels:\n{mentions}", ensure_period=False),
            ephemeral=True,
        )

    @devtool.sub_command_group(name="setcode")
    async def devtool_setcode(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Subcommands for storing product config codes."""
        del inter

    async def _setcode_for_product(
        self,
        inter: disnake.AppCmdInter[Spooky],
        product: CodeProductOption,
        bundle: CodeBundleOption,
        branch: CodeBranchOption,
        color: CodeColorOption | None,
        code: str,
        version: str,
    ) -> None:
        """Update the stored code for a slot without sending any buyer messages."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        role_id = self._role_for_code_slot(bundle=bundle, branch=branch)
        if role_id is None:
            await inter.followup.send(
                embed=status_card(False, "Unable to resolve code slot role."),
                ephemeral=True,
            )
            return

        async with get_session() as session:
            existing_code = (
                await session.execute(
                    select(BuyerCode)
                    .where(
                        BuyerCode.product == product,
                        BuyerCode.role_id == int(role_id),
                        BuyerCode.color.is_(color) if color is None else BuyerCode.color == color,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

            if existing_code is None:
                session.add(
                    BuyerCode(
                        role_id=int(role_id),
                        product=product,
                        bundle=bundle,
                        branch=branch,
                        color=color,
                        code=code,
                        version=version,
                    )
                )
            else:
                existing_code.bundle = bundle
                existing_code.product = product
                existing_code.branch = branch
                existing_code.color = color
                existing_code.code = code
                existing_code.version = version

            await session.flush()

        await inter.followup.send(
            embed=status_card(
                True,
                (
                    "Stored code update successfully. "
                    "Use /devtool sendmembercode or /devtool sendallmembercode to publish updates."
                ),
            ),
            ephemeral=True,
        )

    @devtool_setcode.sub_command(name="memesense")
    async def devtool_setcode_memesense(
        self,
        inter: disnake.AppCmdInter[Spooky],
        bundle: CodeBundleOption,
        branch: CodeBranchOption,
        color: CodeColorOption,
        code: str,
        version: str,
    ) -> None:
        """Update stored Memesense config code for a slot."""
        await self._setcode_for_product(
            inter=inter,
            product="memesense",
            bundle=bundle,
            branch=branch,
            color=color,
            code=code,
            version=version,
        )

    @devtool_setcode.sub_command(name="fatality")
    async def devtool_setcode_fatality(
        self,
        inter: disnake.AppCmdInter[Spooky],
        bundle: CodeBundleOption,
        branch: CodeBranchOption,
        code: str,
        version: str,
    ) -> None:
        """Update stored Fatality config code for a slot."""
        await self._setcode_for_product(
            inter=inter,
            product="fatality",
            bundle=bundle,
            branch=branch,
            color=None,
            code=code,
            version=version,
        )

    @devtool.sub_command_group(name="send")
    async def devtool_send(self, inter: disnake.AppCmdInter[Spooky]) -> None:
        """Subcommands for publishing config summaries."""
        del inter

    @devtool_send.sub_command(name="member")
    async def devtool_sendmembercode(
        self,
        inter: disnake.AppCmdInter[Spooky],
        member: disnake.Member,
    ) -> None:
        """Send latest role-based config access summary for a selected member."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        tracked_roles = {
            SEMI_LEGIT_MAIN_ROLE_ID,
            SEMI_LEGIT_VISUAL_ROLE_ID,
            SEMI_RAGE_MAIN_ROLE_ID,
            SEMI_RAGE_VISUAL_ROLE_ID,
            STATS_BOOSTER_ROLE_ID,
        }

        await inter.response.defer(ephemeral=True)

        async with get_session() as session:
            code_rows = (
                (
                    await session.execute(
                        select(BuyerCode).where(BuyerCode.role_id.in_(tracked_roles))
                    )
                )
                .scalars()
                .all()
            )
            channels = (
                await session.execute(
                    select(BuyerChannel.channels)
                    .where(BuyerChannel.user_id == int(member.id))
                    .limit(1)
                )
            ).scalar_one_or_none()

        codes_by_product_role = group_codes_by_product_and_role(code_rows)
        summary = build_member_code_summary(
            member=member,
            codes_by_product_role=codes_by_product_role,
        )

        if channels is None or "config_codes_thread" not in channels:
            await inter.edit_original_response(
                embed=status_card(False, f"No CONFIG CODES thread is stored for {member.mention}."),
            )
            return

        config_thread = self.bot.get_channel(int(channels["config_codes_thread"]))
        if not isinstance(config_thread, disnake.Thread):
            await inter.edit_original_response(
                embed=status_card(False, "Stored CONFIG CODES thread is missing or inaccessible."),
            )
            return

        await config_thread.send(summary)
        await inter.edit_original_response(
            embed=status_card(
                True, f"Sent latest config access summary to {config_thread.mention}."
            ),
        )

    @devtool_send.sub_command(name="all")
    async def devtool_sendallmembercode(
        self,
        inter: disnake.AppCmdInter[Spooky],
        note: str,
    ) -> None:
        """Send role-based config summaries to all persisted buyer config threads."""
        if inter.author.id != OWNER_ID:
            await inter.response.send_message(
                embed=status_card(False, "Only the configured owner can use /devtool."),
                ephemeral=True,
            )
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message(
                embed=status_card(False, "This command can only be used in a guild."),
                ephemeral=True,
            )
            return

        tracked_roles = {
            SEMI_LEGIT_MAIN_ROLE_ID,
            SEMI_LEGIT_VISUAL_ROLE_ID,
            SEMI_RAGE_MAIN_ROLE_ID,
            SEMI_RAGE_VISUAL_ROLE_ID,
            STATS_BOOSTER_ROLE_ID,
        }

        await inter.response.defer(ephemeral=True)

        async with get_session() as session:
            code_rows = (
                (
                    await session.execute(
                        select(BuyerCode).where(BuyerCode.role_id.in_(tracked_roles))
                    )
                )
                .scalars()
                .all()
            )
            buyer_rows = (
                (await session.execute(select(BuyerChannel.user_id, BuyerChannel.channels)))
                .tuples()
                .all()
            )

        if not buyer_rows:
            await inter.edit_original_response(
                embed=status_card(False, "No buyer channels are stored yet."),
            )
            return

        codes_by_product_role = group_codes_by_product_and_role(code_rows)
        sent = 0
        missing_threads = 0
        missing_members = 0

        for user_id, channels in buyer_rows:
            member = guild.get_member(int(user_id))
            if member is None:
                missing_members += 1
                continue

            config_thread = self.bot.get_channel(int(channels["config_codes_thread"]))
            if not isinstance(config_thread, disnake.Thread):
                missing_threads += 1
                continue

            summary = build_member_code_summary(
                member=member,
                codes_by_product_role=codes_by_product_role,
                note=note,
            )
            with suppress(Exception):
                await config_thread.send(summary)
                sent += 1

        await inter.edit_original_response(
            embed=status_card(
                True,
                (
                    f"Sent config summaries to {sent}/{len(buyer_rows)} buyer threads. "
                    f"Missing members: {missing_members}. "
                    f"Missing/inaccessible threads: {missing_threads}."
                ),
            ),
        )

    @staticmethod
    def _resolve_permission_name(raw: str) -> str | None:
        """Resolve user-entered text to an :class:`AppPermission` value via fuzzing."""
        candidates = [permission.value for permission in AppPermission]
        matches = process.extract(raw, candidates, limit=1)
        if not matches:
            return None

        best_match, score = matches[0]
        if score < FUZZY_PERMISSION_SCORE_THRESHOLD:
            return None
        return best_match

    @staticmethod
    def _buyer_member_overwrite() -> disnake.PermissionOverwrite:
        """Return strict member overwrite for buyer forums."""
        overwrite_payload = {permission.value: False for permission in AppPermission}
        overwrite = disnake.PermissionOverwrite(**overwrite_payload)
        overwrite.view_channel = True
        overwrite.send_messages_in_threads = True
        overwrite.read_message_history = True
        overwrite.send_messages = False
        overwrite.create_public_threads = False
        overwrite.create_private_threads = False
        return overwrite

    @staticmethod
    def _extract_created_thread(result: object) -> disnake.Thread | None:
        """Extract thread object from forum create_thread return payload."""
        if isinstance(result, disnake.Thread):
            return result
        if isinstance(result, tuple) and result:
            maybe_thread = result[0]
            if isinstance(maybe_thread, disnake.Thread):
                return maybe_thread
        return None

    @staticmethod
    def _role_for_code_slot(*, bundle: CodeBundleOption, branch: CodeBranchOption) -> int | None:
        """Resolve the access role tied to a config bundle/branch slot."""
        role_map: dict[tuple[CodeBundleOption, CodeBranchOption], int] = {
            ("Semi-Legit", "Main Branch"): SEMI_LEGIT_MAIN_ROLE_ID,
            ("Semi-Legit", "Visual"): SEMI_LEGIT_VISUAL_ROLE_ID,
            ("Semi-Rage", "Main Branch"): SEMI_RAGE_MAIN_ROLE_ID,
            ("Semi-Rage", "Visual"): SEMI_RAGE_VISUAL_ROLE_ID,
            ("Stats-Booster", "Main Branch"): STATS_BOOSTER_ROLE_ID,
            ("Stats-Booster", "Visual"): STATS_BOOSTER_ROLE_ID,
        }
        return role_map.get((bundle, branch))

    @devtool_permission.autocomplete("permission")
    async def permission_autocomplete(
        self,
        inter: disnake.AppCmdInter[Spooky],
        user_input: str,
    ) -> list[str]:
        """Return up to 25 fuzzy-matched permission choices for slash autocomplete."""
        del inter
        candidates = [permission.value for permission in AppPermission]
        if not user_input.strip():
            return candidates[:MAX_PERMISSION_CHOICES]

        ranked = process.extract(user_input, candidates, limit=MAX_PERMISSION_CHOICES)
        seen: set[str] = set()
        results: list[str] = []
        for choice, score in ranked:
            if score < FUZZY_PERMISSION_SCORE_THRESHOLD:
                continue
            if choice in seen:
                continue
            seen.add(choice)
            results.append(choice)

        if results:
            return results
        return candidates[:MAX_PERMISSION_CHOICES]
