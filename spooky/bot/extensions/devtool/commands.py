"""Slash commands for developer-only maintenance utilities."""

from __future__ import annotations

from typing import Literal

import disnake
from disnake.ext import commands
from spooky.bot import Spooky
from spooky.core.checks import fakeperms_or_discordperm
from spooky.db import get_session
from spooky.ext.components.v2.card import status_card
from spooky.ext.constants import OWNER_ID, VAC_TIPS_CHANNEL_ID
from spooky.ext.message import render_buyer_welcome
from spooky.models.entities.permissions import AppPermission, UserPermissionOverride
from sqlalchemy import delete, select
from thefuzz import process

PermissionAction = Literal["Add", "Remove"]
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
        await inter.response.send_message("Choose a subcommand.", ephemeral=True)

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

    @devtool.sub_command(name="createbuyer")
    async def devtool_createbuyer(
        self,
        inter: disnake.AppCmdInter[Spooky],
        member: disnake.Member,
    ) -> None:
        """Create a private buyer forum visible only to the selected member.

        Parameters
        ----------
        member : disnake.Member
            Member who should have access to the created buyer forum.
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

        everyone_overwrite = disnake.PermissionOverwrite(view_channel=False)
        member_overwrite = self._buyer_member_overwrite()

        forum_name = f"buyer-{member.display_name}".lower().replace(" ", "-")
        forum = await guild.create_forum_channel(
            name=forum_name[:100],
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

        await forum.create_thread(name="INTRODUCTION", content=welcome_message)
        await forum.create_thread(
            name="CONFIG CODES",
            content="Config codes for this buyer will be posted in this thread.",
        )

        await inter.response.send_message(
            embed=status_card(
                True,
                f"Created buyer forum {forum.mention} for {member.mention}",
            ),
            ephemeral=True,
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
