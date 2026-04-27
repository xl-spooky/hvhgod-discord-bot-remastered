"""Premium SKU synchronization helpers.

This module keeps the locally persisted premium SKU catalog aligned with the
entries known to the running bot. Premium entitlement ownership is now resolved
exclusively through Discords API responses; cleanup work here focuses on
pruning cached SKUs and deleting any expired test entitlements that Discord has
not already cleaned up.

Usage
-----
Typically invoked during bot startup or scheduled maintenance::

    from spooky.premium.sync import sync_entitlements
    await sync_entitlements(bot)

Notes
-----
- Synchronization requires SKU mappings to be initialized first through
  :func:`spooky.premium.cache.fill_bot_sku_cache`.
- Entitlement ownership is no longer persisted locally; stale SKU records are
  removed when they disappear from the bots cache. Expired entitlements are
  deleted here only if Discord still returns them after their end time.
"""

from __future__ import annotations

import contextlib

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.db import get_session
from spooky.models.entities.premium import PremiumSKU
from spooky.premium.enums import PremiumProduct
from sqlalchemy import delete, select

from ..utils import guard_db_ready

__all__ = ["sync_entitlements"]


async def _prune_missing_skus(current_sku_ids: set[int] | None) -> None:
    """Delete persisted SKUs that are no longer known to the bot."""
    if not current_sku_ids:
        logger.debug(
            "skipping premium sku pruning; no current sku ids are cached for comparison",
        )
        return

    async with get_session() as session:
        result = await session.execute(select(PremiumSKU.sku_id))
        stored_ids = {int(row) for row in result.scalars().all()}
        if not stored_ids:
            return

        stale_ids = stored_ids - current_sku_ids
        if not stale_ids:
            return

        await session.execute(delete(PremiumSKU).where(PremiumSKU.sku_id.in_(list(stale_ids))))
        await session.flush()

    logger.info("pruned {} stale premium skus", len(stale_ids))


async def _cleanup_expired_entitlements(bot: Spooky) -> int:
    """Delete expired Spooky Premium entitlements if Discord has not already."""
    sku_id = getattr(bot, "product_to_sku", {}).get(PremiumProduct.SPOOKY_PREMIUM)
    if sku_id is None:
        logger.debug(
            "skipping premium entitlement cleanup; spooky premium sku is not mapped",
        )
        return 0

    expired = 0
    entitlements = bot.entitlements(
        skus=[disnake.Object(id=sku_id)],
        exclude_ended=False,
        exclude_deleted=False,
    )

    async for entitlement in entitlements:
        if entitlement.application_id != bot.application_id:
            continue
        if int(entitlement.sku_id) != int(sku_id):
            continue
        if entitlement.ends_at is None:
            continue
        if entitlement.ends_at > disnake.utils.utcnow():
            continue
        if entitlement.deleted:
            continue

        with contextlib.suppress(disnake.HTTPException):
            await entitlement.delete()
            expired += 1

    if not expired:
        logger.debug(
            "no expired spooky premium entitlements required manual cleanup; "
            "assuming Discord handled them",
        )

    return expired


async def sync_entitlements(bot: Spooky) -> None:
    """Prune stale premium SKUs from the database.

    Parameters
    ----------
    bot:
        The active :class:`~spooky.bot.Spooky` instance, used to query entitlements
        and determine product-to-SKU mappings.

    Returns
    -------
    None
        Performs cleanup as a side effect.

    Notes
    -----
    - If the database is unavailable or not ready (checked via
      :func:`spooky.premium.utils.guard_db_ready`), the pruning step is skipped.
    - Entitlement ownership is resolved dynamically through the Discord API,
      so no entitlement data is persisted locally during this task.
    """
    if not await guard_db_ready(bot):
        return

    await bot.wait_until_ready()

    cached_skus = getattr(bot, "cached_skus", {}) or {}
    current_sku_ids = {int(sku_id) for sku_id in cached_skus}
    await _prune_missing_skus(current_sku_ids)

    removed = await _cleanup_expired_entitlements(bot)
    if removed:
        logger.info("removed {} expired premium entitlements", removed)

    logger.debug(
        "premium entitlements are now resolved via the Discord API; no database sync required"
    )
