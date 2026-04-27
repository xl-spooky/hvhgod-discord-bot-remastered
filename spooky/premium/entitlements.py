"""Runtime helpers for verifying premium product ownership.

This module now queries Discords entitlement API directly to determine whether
a user owns a premium product such as *Video Saver*. Local database state is no
longer consulted, ensuring that deleted or missing SKUs are immediately
reflected in access checks.

Usage
-----
Check entitlement ownership within commands or views::

    from spooky.premium.entitlements import user_has_video_saver

    if not await user_has_video_saver(bot, inter.author.id):
        await inter.response.send_message(
            "You need the Video Saver product to use this feature.",
            ephemeral=True,
        )

Notes
-----
- Entitlements are considered valid only if not deleted, not consumed, and not
  expired according to the live API response.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

import disnake
from spooky.bot import Spooky

from .enums import PremiumProduct

__all__ = [
    "guild_has_spooky_premium",
    "user_has_video_saver",
]


async def _api_has_product(
    bot: Spooky,
    *,
    owner_id: int,
    owner_scope: Literal["user", "guild"],
    product: PremiumProduct,
) -> bool:
    """Check live Discord entitlements API for ``owner_id`` ownership.

    Parameters
    ----------
    bot:
        The running :class:`~spooky.bot.Spooky` instance.
    owner_id:
        Discord ID being verified (user or guild depending on ``owner_scope``).
    owner_scope:
        Whether the owner being checked is a ``"user"`` or ``"guild"``.
    product:
        Premium product to match via its corresponding SKU.

    Returns
    -------
    bool
        ``True`` if the Discord API reports at least one active entitlement.

    Notes
    -----
    - Skips any entitlements flagged as ``deleted`` or ``consumed``.
    - Only entitlements mapped to currently cached SKUs are considered valid.
    """
    product_to_sku = getattr(bot, "product_to_sku", {}) or {}
    sku_to_product = getattr(bot, "sku_to_product", {}) or {}

    sku_id = product_to_sku.get(product)
    sku_filter: Sequence[disnake.Object] | None = None
    if sku_id is not None:
        sku_filter = [disnake.Object(id=sku_id)]

    scope_kwargs: dict[str, disnake.User | disnake.Guild]
    if owner_scope == "guild":
        owner = cast(disnake.Guild, disnake.Object(id=owner_id))
        scope_kwargs = {"guild": owner}
    else:
        owner = cast(disnake.User, disnake.Object(id=owner_id))
        scope_kwargs = {"user": owner}

    entitlements = bot.entitlements(
        **scope_kwargs,  # type: ignore[call-arg]
        skus=sku_filter,
        exclude_ended=True,
        exclude_deleted=True,
    )
    application_id = getattr(bot, "application_id", None)
    async for entitlement in entitlements:
        if application_id is not None and entitlement.application_id != application_id:
            continue

        sku_identifier = getattr(entitlement, "sku_id", None)
        if sku_identifier is None:
            continue
        mapped_product = sku_to_product.get(int(sku_identifier))
        if mapped_product != product:
            continue
        if entitlement.deleted or entitlement.consumed:
            continue
        return True
    return False


async def user_has_video_saver(bot: Spooky, user_id: int) -> bool:
    """Return ``True`` if ``user_id`` currently owns the Video Saver entitlement.

    Parameters
    ----------
    bot:
        Active :class:`~spooky.bot.Spooky` instance managing SKUs and entitlements.
    user_id:
        Discord user ID to validate ownership for.

    Returns
    -------
    bool
        ``True`` if the user owns the Video Saver product according to the
        Discord API.

    Examples
    --------
    >>> await user_has_video_saver(bot, 404264989147529217)
    True

    Notes
    -----
    - Entitlement ownership is derived solely from the live Discord API.
    """
    product = PremiumProduct.VIDEO_SAVER
    return await _api_has_product(
        bot,
        owner_id=user_id,
        owner_scope="user",
        product=product,
    )


async def guild_has_spooky_premium(bot: Spooky, guild_id: int) -> bool:
    """Return ``True`` if ``guild_id`` owns the Spooky Premium subscription.

    Parameters
    ----------
    bot:
        Active :class:`~spooky.bot.Spooky` instance managing SKUs and entitlements.
    guild_id:
        Discord guild ID to validate ownership for.

    Returns
    -------
    bool
        ``True`` when the Discord API reports an active Spooky Premium
        entitlement for ``guild_id``.
    """
    product = PremiumProduct.SPOOKY_PREMIUM
    return await _api_has_product(
        bot,
        owner_id=guild_id,
        owner_scope="guild",
        product=product,
    )
