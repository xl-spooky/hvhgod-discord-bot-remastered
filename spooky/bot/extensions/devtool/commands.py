"""Developer tooling cog and premium command suite for Spooky.

This module implements the :class:`DevTools` cog, providing an internal set of
slash commands reserved for developers and maintainers. These utilities support
SKU registration, cache synchronization, and database management for premium
features.

Usage
-----
This cog is automatically registered when the developer tooling extension is
loaded::

    >>> bot.load_extension("spooky.bot.extensions.devtool")

Notes
-----
- All commands are restricted to the internal developer guild.
- The root ``/devtool`` group exposes command clusters for premium SKU
  management and cache inspection.
- Operations may modify both in-memory caches and database records, depending
  on current environment configuration.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal, cast

import disnake
from disnake.ext import commands as disnake_commands
from spooky.bot import Spooky
from spooky.bot.extensions.devtool.constants import DEVELOPER_GUILD_ID
from spooky.bot.extensions.devtool.services import cleanup_conflicting_skus
from spooky.bot.extensions.devtool.utils import ensure_developer_context
from spooky.bot.extensions.settings.guild.panel_tracker import close_guild_panels_for_guild
from spooky.core import checks
from spooky.db import get_session
from spooky.ext.components.v2.card import status_card
from spooky.ext.time import utcnow
from spooky.models.entities.premium import PremiumSKU
from spooky.premium.cache import fill_bot_sku_cache
from spooky.premium.enums import PremiumProduct
from spooky.premium.store import upsert_sku
from sqlalchemy import delete, select

PremiumProductLiteral = Literal["Spooky Premium"]

__all__ = ["DevTools"]

_MAX_SKU_FIELDS = 25
_GUILD_ONLY_CONTEXT = cast(disnake.InteractionContextTypes, disnake.InteractionContextTypes.guild)


class DevTools(disnake_commands.Cog):
    """Cog that exposes developer-only command groups for maintenance tasks.

    The :class:`DevTools` cog contains restricted commands designed to assist
    Spooky developers in diagnosing runtime issues, managing premium SKUs,
    and maintaining cache consistency across environments.
    """

    def __init__(self, bot: Spooky) -> None:
        """Initialize the developer tooling cog.

        Parameters
        ----------
        bot:
            The active :class:`~spooky.bot.Spooky` instance that manages cogs
            and the Discord command tree.
        """
        self.bot = bot

    async def cog_check(self, inter: disnake.GuildCommandInteraction[Spooky]) -> bool:  # type: ignore[override]
        """Ensure that the invoking context is authorized for developer use.

        Parameters
        ----------
        inter:
            The invoking :class:`~disnake.GuildCommandInteraction`.

        Returns
        -------
        bool
            ``True`` if the interaction is from an authorized developer
            context, otherwise ``False``.
        """
        return await ensure_developer_context(inter)

    @disnake_commands.slash_command(
        name="devtool",
        description="Developer maintenance utilities.",
        guild_ids=[DEVELOPER_GUILD_ID],
        contexts=_GUILD_ONLY_CONTEXT,
        extras={"category": "Developer", "hide_from_help": True},
    )
    @disnake_commands.default_member_permissions(administrator=True)  # type: ignore[misc]
    async def devtool(self, _: disnake.GuildCommandInteraction[Spooky]) -> None:
        """Root command group (no-op entry point)."""

    @devtool.sub_command_group(  # type: ignore[misc]
        name="premium",
        description="Premium SKU cache helpers.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def premium(self, _: disnake.GuildCommandInteraction[Spooky]) -> None:
        """Command group for premium SKU and cache management."""

    def _format_missing_cache_entries(self) -> str | None:
        """Format a string of unmapped SKUs from the cache.

        Returns
        -------
        str | None
            A human-readable list of SKU IDs missing from cache mappings, or
            ``None`` if all SKUs are mapped.
        """
        if not self.bot.cached_skus:
            return None

        tracked = set(self.bot.sku_to_product.keys())
        missing: Iterable[int] = (
            sku_id for sku_id in self.bot.cached_skus if sku_id not in tracked
        )
        lines = [str(sku_id) for sku_id in missing]
        if not lines:
            return None
        return "Unmapped cached SKUs: " + ", ".join(lines)

    @staticmethod
    def _normalize_product(product: PremiumProduct | str) -> PremiumProduct:
        """Normalize the given input into a :class:`PremiumProduct` enum.

        Parameters
        ----------
        product:
            Either a string name or an existing :class:`PremiumProduct` enum
            value.

        Returns
        -------
        PremiumProduct
            The corresponding normalized product enumeration.

        Raises
        ------
        ValueError
            If the input cannot be matched to any known product.
        """
        if isinstance(product, PremiumProduct):
            return product

        raw = str(product).strip()
        try:
            return PremiumProduct(raw)
        except ValueError:
            lowered = raw.lower()
            for candidate in PremiumProduct:
                if lowered in candidate.aliases():
                    return candidate
        raise ValueError(f"Unknown premium product: {product!r}")

    def _resolve_spooky_premium_sku(self) -> disnake.SKU | None:
        """Return the mapped Spooky Premium subscription SKU if available."""
        sku_id = self.bot.product_to_sku.get(PremiumProduct.SPOOKY_PREMIUM)
        if sku_id is None:
            return None

        sku = self.bot.cached_skus.get(int(sku_id))
        if sku is None:
            return None

        if sku.type is not disnake.SKUType.subscription:
            return None

        if sku.name.strip().lower() != "spooky premium":
            return None

        return sku

    @staticmethod
    def _premium_buttons() -> list[disnake.ui.Button[disnake.ui.View | None]]:
        """Return common buttons linking to premium resources."""
        components: list[disnake.ui.Button[disnake.ui.View | None]] = [
            disnake.ui.Button(
                label="Our Website",
                style=disnake.ButtonStyle.url,
                url="https://spookybot.org/",
            ),
            disnake.ui.Button(
                label="Subscriptions and Perks",
                style=disnake.ButtonStyle.url,
                url="https://spookybot.org/premium",
            ),
        ]
        return components

    async def _announce_trial_change(
        self,
        guild_id: int,
        *,
        actor: disnake.User | disnake.Member,
        action: Literal["grant", "revoke"],
        ends_at: datetime | None = None,
    ) -> None:
        """Send a public or owner-facing notification about a trial change."""
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            with contextlib.suppress(disnake.HTTPException):
                guild = await self.bot.fetch_guild(guild_id)
        if guild is None:
            return

        level_name = PremiumProduct.SPOOKY_PREMIUM.name.replace("_", " ").title()
        title = (
            "Spooky Premium Trial granted" if action == "grant" else "Spooky Premium Trial revoked"
        )
        end_fragment = (
            f" The trial ends at {disnake.utils.format_dt(ends_at)}."
            if ends_at is not None and action == "grant"
            else ""
        )
        unhappy = " :(" if action == "revoke" else ""
        description = (
            f"`{actor}` {action}ed a trial subscription of level **{level_name}** "
            f"for this server!{end_fragment}\n\n"
            "You can find more about our subscriptions and perks on our website!"
        )

        embed = disnake.Embed(title=title, description=description + unhappy)
        components = self._premium_buttons()

        if guild.public_updates_channel:
            try:
                await guild.public_updates_channel.send(embed=embed, components=components)
            except disnake.Forbidden:
                pass
            else:
                return

        owner = guild.owner
        if owner is None and guild.owner_id is not None:
            try:
                owner = await self.bot.fetch_user(guild.owner_id)
            except disnake.HTTPException:
                owner = None

        if owner is None:
            return

        description = (
            f"`{actor}` {action}ed a trial subscription of level **{level_name}** "
            f"for the **{guild.name}** server!{end_fragment}\n\n"
            "You can find more about our subscriptions and perks on our website!"
        )
        embed.description = description + unhappy

        with contextlib.suppress(disnake.Forbidden):
            await owner.send(embed=embed, components=components)

    @premium.sub_command(
        name="list_skus",
        description="List stored premium SKUs.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def list_skus(self, inter: disnake.GuildCommandInteraction[Spooky]) -> None:
        """Display all stored SKUs registered in the database."""
        await inter.response.defer(ephemeral=True)

        if not checks.db_enabled():
            await inter.edit_original_message(
                content="Database access is disabled; no persisted SKUs are available."
            )
            return

        async with get_session() as session:
            result = await session.execute(select(PremiumSKU))
            records = result.scalars().all()

        embed = disnake.Embed(title="Premium SKU registry")
        if not records:
            embed.description = "No premium SKUs are registered in the database."
        else:
            for record in records[:_MAX_SKU_FIELDS]:
                cached = self.bot.cached_skus.get(int(record.sku_id))
                cache_state = "Cached" if cached else "Not cached"
                try:
                    product = self._normalize_product(record.product)
                except ValueError:
                    product_label = str(record.product)
                else:
                    product_label = product.display_name
                embed.add_field(
                    name=f"{product_label} — {record.sku_id}",
                    value=(f"Name: {record.name}\nType: {record.sku_type}\nCache: {cache_state}"),
                    inline=False,
                )
            if len(records) > _MAX_SKU_FIELDS:
                embed.set_footer(text=f"Only the first {_MAX_SKU_FIELDS} entries are shown.")

        trailing = self._format_missing_cache_entries()
        if trailing:
            if embed.description:
                embed.description += f"\n\n{trailing}"
            else:
                embed.description = trailing

        await inter.edit_original_message(embed=embed)

    @premium.sub_command(
        name="reload_cached_skus",
        description="Refresh premium SKUs from Discord.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def reload_cached_skus(self, inter: disnake.GuildCommandInteraction[Spooky]) -> None:
        """Reload cached premium SKUs directly from Discord."""
        await inter.response.defer(ephemeral=True)
        await fill_bot_sku_cache(self.bot)

        embed = disnake.Embed(title="Premium cache refreshed")
        embed.add_field(name="Cached SKUs", value=str(len(self.bot.cached_skus)))
        embed.add_field(name="Mapped products", value=str(len(self.bot.product_to_sku)))
        trailing = self._format_missing_cache_entries()
        if trailing:
            embed.description = trailing

        await inter.edit_original_message(embed=embed)

    @premium.sub_command(
        name="register_sku",
        description="Register a Discord SKU.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def register_sku(
        self,
        inter: disnake.GuildCommandInteraction[Spooky],
        sku_id: str,
        product: PremiumProduct = disnake_commands.Param(
            description="Premium product unlocked by the SKU."
        ),
    ) -> None:
        """Register and associate a Discord SKU with a premium product.

        Parameters
        ----------
        sku_id:
            The Discord SKU ID to register.
        product:
            The premium product this SKU unlocks.
        """
        await inter.response.defer(ephemeral=True)

        try:
            sku_id_int = int(sku_id)
        except ValueError:
            await inter.edit_original_message(content="SKU ID must be an integer.")
            return

        product_enum = self._normalize_product(product)

        skus = await self.bot.skus()
        sku = disnake.utils.get(skus, id=sku_id_int)
        if sku is None:
            await inter.edit_original_message(
                content=(
                    "The provided SKU could not be found. Ensure it is published and available."
                )
            )
            return

        if int(sku.application_id) != self.bot.application_id:
            await inter.edit_original_message(
                content=(
                    "The provided SKU belongs to a different application. "
                    "Select an SKU created for this bot."
                )
            )
            return

        expected_type = product_enum.expected_sku_type
        if sku.type is not expected_type:
            await inter.edit_original_message(
                content=(
                    "The provided SKU type does not match the product requirements. "
                    f"Expected `{expected_type.name}` but received `{sku.type.name}`."
                )
            )
            return

        if not sku.flags.available:
            await inter.edit_original_message(
                content=(
                    "The provided SKU is not currently published. Publish the SKU in the "
                    "Discord developer portal before registering it."
                )
            )
            return

        previous = self.bot.product_to_sku.get(product_enum)
        if previous and previous != sku_id_int:
            self.bot.sku_to_product.pop(previous, None)

        self.bot.cached_skus[sku_id_int] = sku
        self.bot.sku_to_product[sku_id_int] = product_enum
        self.bot.product_to_sku[product_enum] = sku_id_int

        if checks.db_enabled():
            await upsert_sku(sku, product_enum)
            await cleanup_conflicting_skus(product_enum, sku_id_int)

        embed = disnake.Embed(title="SKU registered")
        embed.description = f"Mapped **{product_enum.display_name}** to SKU ``{sku_id_int}``."
        await inter.edit_original_message(embed=embed)

    @premium.sub_command(
        name="delete_sku",
        description="Delete a registered SKU.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def delete_sku(self, inter: disnake.GuildCommandInteraction[Spooky], sku_id: str) -> None:
        """Delete a registered SKU from cache and persistent storage.

        Parameters
        ----------
        sku_id:
            The SKU ID to remove from the registry.
        """
        await inter.response.defer(ephemeral=True)

        try:
            sku_id_int = int(sku_id)
        except ValueError:
            await inter.edit_original_message(content="SKU ID must be an integer.")
            return

        cached = self.bot.cached_skus.pop(sku_id_int, None)
        product = self.bot.sku_to_product.pop(sku_id_int, None)
        if product is not None:
            self.bot.product_to_sku.pop(product, None)

        if checks.db_enabled():
            async with get_session() as session:
                await session.execute(delete(PremiumSKU).where(PremiumSKU.sku_id == sku_id_int))
                await session.flush()

        embed = disnake.Embed(title="SKU deleted from database")
        label = cached.name if cached else str(sku_id_int)
        embed.add_field(name=label, value=f"`{sku_id_int}`", inline=False)
        embed.description = (
            "The SKU was removed from the database and cache. To fully delete it, "
            "unpublish or delete the SKU from the Discord developer portal."
        )
        await inter.edit_original_message(embed=embed)

    @premium.sub_command(
        name="grant",
        description="Grant a Spooky Premium monthly subscription trial to a guild.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def grant(
        self,
        inter: disnake.GuildCommandInteraction[Spooky],
        product: PremiumProductLiteral = disnake_commands.Param(
            description="Premium product to grant.",
            default="Spooky Premium",
        ),
        guild_id: str = disnake_commands.Param(description="Guild ID to receive the trial."),
    ) -> None:
        """Grant a Spooky Premium monthly trial entitlement to a guild.

        Parameters
        ----------
        product:
            Literal premium product selector. Only ``"Spooky Premium"`` is supported.
        guild_id:
            The target guild ID that should receive the Spooky Premium entitlement.

        Workflow
        --------
        1. Validate the literal product selection and parse the guild ID.
        2. Confirm no active Spooky Premium entitlement exists for the guild.
        3. Create a monthly entitlement and rely on Discord to expire it after the
           billing period.
        4. Respond with a report-card status embed and announce the grant to the guild.
        """
        await inter.response.defer(ephemeral=True)

        try:
            guild_identifier = int(guild_id)
        except ValueError:
            await inter.edit_original_message(
                embed=status_card(False, "Guild ID must be an integer."),
            )
            return

        if product != "Spooky Premium":
            await inter.edit_original_message(
                embed=status_card(False, "Unsupported premium product."),
            )
            return

        sku = self._resolve_spooky_premium_sku()
        if sku is None:
            await inter.edit_original_message(
                embed=status_card(
                    False,
                    "Spooky Premium is not registered or is not a monthly SKU. "
                    "Register the subscription SKU before granting trials.",
                ),
            )
            return

        owner = cast(disnake.Guild, disnake.Object(id=guild_identifier))
        entitlements = self.bot.entitlements(
            guild=owner,
            skus=[disnake.Object(id=sku.id)],
            exclude_ended=True,
            exclude_deleted=True,
        )

        async for entitlement in entitlements:
            if entitlement.application_id != self.bot.application_id:
                continue
            if int(entitlement.sku_id) != int(sku.id):
                # disnake's EntitlementIterator ignores sku filters; enforce locally.
                continue
            if entitlement.deleted or entitlement.consumed:
                continue
            await inter.edit_original_message(
                embed=status_card(
                    None,
                    "This guild already has an active Spooky Premium entitlement.",
                )
            )
            return

        expires_at = utcnow() + timedelta(days=30)

        try:
            entitlement = await self.bot.create_entitlement(
                sku=disnake.Object(id=sku.id),
                owner=owner,
            )
        except disnake.HTTPException as exc:
            await inter.edit_original_message(
                embed=status_card(False, f"Failed to grant Spooky Premium: {exc}"),
            )
            return

        await inter.edit_original_message(
            embed=status_card(
                True,
                "Granted Spooky Premium (monthly) to guild "
                f"`{guild_identifier}`. Entitlement ID: `{entitlement.id}`.",
                ensure_period=False,
            )
        )

        await self._announce_trial_change(
            guild_identifier,
            actor=inter.author,
            action="grant",
            ends_at=expires_at,
        )

    @premium.sub_command(
        name="revoke",
        description="Revoke a Spooky Premium trial from a guild.",
        extras={"category": "Developer", "hide_from_help": True},
    )
    async def revoke(
        self,
        inter: disnake.GuildCommandInteraction[Spooky],
        product: PremiumProductLiteral = disnake_commands.Param(
            description="Premium product to revoke.",
            default="Spooky Premium",
        ),
        guild_id: str = disnake_commands.Param(description="Guild ID losing the trial."),
    ) -> None:
        """Revoke an active Spooky Premium monthly trial from a guild.

        Parameters
        ----------
        product:
            Literal premium product selector. Only ``"Spooky Premium"`` is supported.
        guild_id:
            The target guild ID whose Spooky Premium entitlement should be revoked.

        Workflow
        --------
        1. Validate the literal product selection and parse the guild ID.
        2. Locate the active Spooky Premium entitlement for the guild.
        3. Delete the entitlement and acknowledge via a report-card status embed.
        4. Notify the guild through the public updates channel or its owner.
        """
        await inter.response.defer(ephemeral=True)

        try:
            guild_identifier = int(guild_id)
        except ValueError:
            await inter.edit_original_message(
                embed=status_card(False, "Guild ID must be an integer."),
            )
            return

        if product != "Spooky Premium":
            await inter.edit_original_message(
                embed=status_card(False, "Unsupported premium product."),
            )
            return

        sku = self._resolve_spooky_premium_sku()
        if sku is None:
            await inter.edit_original_message(
                embed=status_card(
                    False,
                    "Spooky Premium is not registered or is not a monthly SKU. "
                    "Register the subscription SKU before revoking trials.",
                ),
            )
            return

        owner = cast(disnake.Guild, disnake.Object(id=guild_identifier))
        entitlements = self.bot.entitlements(
            guild=owner,
            skus=[disnake.Object(id=sku.id)],
            exclude_ended=False,
            exclude_deleted=False,
        )

        found_matching = False
        revoked = False
        async for entitlement in entitlements:
            if entitlement.application_id != self.bot.application_id:
                continue
            if int(entitlement.sku_id) != int(sku.id):
                # EntitlementIterator currently ignores sku filters; enforce locally.
                continue
            if entitlement.deleted:
                continue
            found_matching = True
            try:
                await entitlement.delete()
            except disnake.NotFound:
                # Ignore non-test entitlements that cannot be deleted.
                continue
            except disnake.HTTPException as exc:
                await inter.edit_original_message(
                    embed=status_card(False, f"Failed to revoke Spooky Premium: {exc}"),
                )
                return
            revoked = True

        if not revoked:
            if found_matching:
                await inter.edit_original_message(
                    embed=status_card(
                        False,
                        (
                            "Spooky Premium entitlements exist for this guild, but none could be "
                            "revoked. Only test entitlements created via this tool can be deleted."
                        ),
                    ),
                )
                return
            await inter.edit_original_message(
                embed=status_card(None, "No Spooky Premium entitlement found for this guild."),
            )
            return

        await inter.edit_original_message(
            embed=status_card(
                True,
                f"Removed Spooky Premium access for guild `{guild_identifier}`.",
                ensure_period=False,
            )
        )
        await close_guild_panels_for_guild(guild_identifier)

        await self._announce_trial_change(
            guild_identifier,
            actor=inter.author,
            action="revoke",
            ends_at=None,
        )
