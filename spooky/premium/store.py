"""Persistence helpers for premium SKUs.

This module provides a database upsert utility for premium SKUs. Entitlement
state is resolved directly through Discords API, so no entitlement persistence
helpers remain here.

Usage
-----
Used by cache synchronization and developer tooling::

    from spooky.premium.store import upsert_sku

    await upsert_sku(sku, PremiumProduct.VIDEO_SAVER)

Notes
-----
- The helper acquires its own :func:`spooky.db.get_session` context.
- Timestamp fields (`created_at`, `updated_at`) are refreshed automatically.
- Entitlements are resolved directly via the Discord API rather than persisted
  locally.
"""

from __future__ import annotations

from datetime import UTC, datetime

import disnake
from spooky.db import get_session
from spooky.models.entities.premium import PremiumSKU

from .enums import PremiumProduct

__all__ = ["upsert_sku"]


async def upsert_sku(sku: disnake.SKU, product: PremiumProduct) -> None:
    """Create or update a :class:`~spooky.models.entities.premium.PremiumSKU` row.

    Parameters
    ----------
    sku:
        Discord :class:`~disnake.SKU` object representing the catalog entry.
    product:
        The :class:`~spooky.premium.enums.PremiumProduct` this SKU unlocks.

    Returns
    -------
    None
        The SKU record is persisted as a side effect.

    Notes
    -----
    - If the SKU already exists, its fields are updated with the latest values.
    - If the SKU does not exist, a new record is inserted with `created_at`
      and `updated_at` timestamps.
    - Called internally by :func:`spooky.premium.cache.fill_bot_sku_cache` and
      developer tooling commands.
    """
    async with get_session() as session:
        instance = await session.get(PremiumSKU, int(sku.id))
        payload = {
            "sku_id": int(sku.id),
            "product": product,
            "name": sku.name,
            "sku_type": sku.type.name,
            "application_id": int(sku.application_id),
            "updated_at": datetime.now(UTC),
        }
        if instance is None:
            payload["created_at"] = payload["updated_at"]
            session.add(PremiumSKU(**payload))
        else:
            for key, value in payload.items():
                setattr(instance, key, value)
        await session.flush()


async def upsert_entitlement(*args: object, **kwargs: object) -> None:
    """Raise an error for removed premium entitlement persistence.

    Premium entitlement persistence has been removed in favor of relying on the
    live Discord API. Callers should drop database writes and use
    :func:`spooky.premium.entitlements.user_has_video_saver` to verify
    ownership instead.
    """
    raise RuntimeError("Premium entitlement persistence has been removed; rely on the Discord API")
