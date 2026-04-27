"""Service helpers for the developer tooling extension.

This module provides coroutine utilities used by the developer command suite to
perform database maintenance and consistency checks. These helpers are designed
to operate safely within transactional contexts and are typically invoked from
commands under :mod:`spooky.bot.extensions.devtool`.

Usage
-----
The :func:`cleanup_conflicting_skus` coroutine is used internally by
``/devtool premium register_sku`` to ensure SKU mappings remain unique::

    await cleanup_conflicting_skus(product, sku_id)

Notes
-----
- Database operations are skipped when persistence is disabled via
  :func:`spooky.core.checks.db_enabled`.
- These utilities should not raise exceptions under normal operation; errors
  indicate misconfiguration or schema inconsistency.
"""

from __future__ import annotations

from spooky.core import checks
from spooky.db import get_session
from spooky.models.entities.premium import PremiumSKU
from spooky.premium.enums import PremiumProduct
from sqlalchemy import delete

__all__ = ["cleanup_conflicting_skus"]


async def cleanup_conflicting_skus(product: PremiumProduct, sku_id: int) -> None:
    """Remove redundant or outdated SKU entries for a given product.

    Parameters
    ----------
    product:
        The :class:`~spooky.premium.enums.PremiumProduct` whose SKU mappings
        should be cleaned.
    sku_id:
        The active SKU ID to preserve in the database.

    Returns
    -------
    None
        This coroutine performs cleanup as a side effect.

    Notes
    -----
    - Deletes all rows where the stored ``product`` matches but the ``sku_id``
      differs.
    - Automatically skips execution if the database is disabled.
    """
    if not checks.db_enabled():
        return

    async with get_session() as session:
        await session.execute(
            delete(PremiumSKU).where(
                PremiumSKU.product == product,
                PremiumSKU.sku_id != sku_id,
            )
        )
        await session.flush()
