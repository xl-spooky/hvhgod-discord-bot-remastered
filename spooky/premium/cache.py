"""Helpers for populating and maintaining the bot's premium SKU cache.

This module implements the synchronization logic that links Discords catalog
(SKUs) with Spookys internal premium product registry. It ensures the bots
in-memory SKU maps are accurate and that persisted SKU data in the database
remains consistent with the current Discord application catalog.

Usage
-----
Typically invoked during bot startup or via developer commands::

    from spooky.premium.cache import fill_bot_sku_cache

    await fill_bot_sku_cache(bot)

Notes
-----
- This helper automatically filters out unpublished SKUs
  (``sku.flags.available`` must be ``True``).
- SKU mappings are inferred based on normalized name matches against
  :class:`~spooky.premium.enums.PremiumProduct` aliases.
- The database is updated opportunistically if persistence is enabled.
"""

from __future__ import annotations

from collections.abc import Mapping

import disnake
from loguru import logger
from spooky.bot import Spooky
from spooky.core import checks
from spooky.db import get_session
from spooky.models.entities.premium import PremiumSKU
from sqlalchemy import select

from .enums import PremiumProduct
from .store import upsert_sku

__all__ = ["fill_bot_sku_cache"]

# Basic mapping between normalized SKU names and catalog products. This keeps the
# implementation simple until we expose richer configuration.
_PRODUCT_LOOKUP: Mapping[str, PremiumProduct] = {
    alias: product for product in PremiumProduct for alias in product.aliases()
}


def _resolve_product_for_sku(sku: disnake.SKU) -> PremiumProduct | None:
    """Attempt to resolve a Discord SKU into a known PremiumProduct.

    Parameters
    ----------
    sku:
        The :class:`~disnake.SKU` object to classify.

    Returns
    -------
    PremiumProduct | None
        The resolved premium product, or ``None`` if no alias match is found.
    """
    name = sku.name.strip().lower()
    return _PRODUCT_LOOKUP.get(name)


async def fill_bot_sku_cache(bot: Spooky) -> None:
    """Populate in-memory SKU caches and reconcile database persistence.

    Parameters
    ----------
    bot:
        The active :class:`~spooky.bot.Spooky` instance whose SKU maps should
        be filled.

    Returns
    -------
    None
        Performs side effects on ``bot`` and optionally the database.

    Notes
    -----
    - Awaits :meth:`~spooky.bot.Spooky.wait_until_ready` to ensure startup
      readiness before calling :meth:`~spooky.bot.Spooky.skus`.
    - Populates the following bot attributes:

      - ``bot.cached_skus`` — mapping of SKU IDs to :class:`~disnake.SKU`
        objects (only available ones).
      - ``bot.product_to_sku`` — mapping of :class:`~spooky.premium.enums.PremiumProduct`
        to SKU IDs.
      - ``bot.sku_to_product`` — reverse mapping from SKU ID to product.

    - Persists any newly discovered SKU mappings to the database if
      persistence is enabled.
    - Logs diagnostics on missing or unpublished SKUs.
    """
    await bot.wait_until_ready()
    skus = await bot.skus()
    available = [sku for sku in skus if sku.flags.available]
    bot.cached_skus = {int(sku.id): sku for sku in available}

    product_to_sku: dict[PremiumProduct, int] = {}
    sku_to_product: dict[int, PremiumProduct] = {}

    persisted_rows: list[PremiumSKU] = []
    if checks.db_enabled():
        async with get_session() as session:
            result = await session.execute(select(PremiumSKU))
            persisted_rows = list(result.scalars().all())

        for row in persisted_rows:
            sku = bot.cached_skus.get(int(row.sku_id))
            if sku is None:
                logger.debug("persisted premium sku {} is not currently available", row.sku_id)
                continue
            product_to_sku[row.product] = int(row.sku_id)
            sku_to_product[int(row.sku_id)] = row.product

    for sku in available:
        product = _resolve_product_for_sku(sku)
        if product is None or product in product_to_sku:
            continue
        product_to_sku[product] = int(sku.id)
        sku_to_product[int(sku.id)] = product

    bot.product_to_sku = product_to_sku
    bot.sku_to_product = sku_to_product

    logger.info(
        "cached {} premium skus (mapped={})",
        len(bot.cached_skus),
        len(product_to_sku),
    )

    if checks.db_enabled():
        for product, sku_id in product_to_sku.items():
            sku = bot.cached_skus.get(sku_id)
            if sku is None:
                continue
            await upsert_sku(sku, product)

        persisted_products = {row.product for row in persisted_rows}
        persisted_products.update(product_to_sku.keys())
        missing = set(PremiumProduct) - persisted_products
        if missing:
            logger.debug(
                "missing persisted premium skus: {}",
                ", ".join(p.value for p in missing),
            )
