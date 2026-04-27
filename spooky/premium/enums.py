"""Enumerations describing premium catalog offerings.

The premium catalog defines symbolic identifiers for all purchasable products
exposed by the bot. Each member of :class:`PremiumProduct` corresponds to a
distinct Discord SKU and is responsible for identifying what premium feature
set the user unlocks.

Currently, the catalog includes two products:

- *Video Saver*, which grants access to the Instagram and TikTok media-saving
  experience.
- *Spooky Premium*, a monthly subscription that unlocks premium features for
  partner bots.

Usage
-----
Example lookup by enum::

    from spooky.premium.enums import PremiumProduct

    product = PremiumProduct.VIDEO_SAVER
    print(product.display_name)  # "Video Saver"

Notes
-----
- Additional products can be appended as the premium ecosystem expands.
- Each member can define its own SKU type and name aliases to simplify
  auto-matching within :mod:`spooky.premium.cache`.
"""

from __future__ import annotations

from enum import Enum

from disnake import SKUType

__all__ = ["PremiumProduct"]


class PremiumProduct(str, Enum):
    """Symbolic identifiers for the supported premium catalog entries.

    Each value corresponds to a Discord SKU registered for the bots
    application, used to determine user entitlements and synchronize catalog
    ownership.

    Attributes
    ----------
    VIDEO_SAVER:
        Unlocks the cross-platform *Video Saver* experience, allowing users to
        store and manage Instagram/TikTok media.

    Examples
    --------
    >>> PremiumProduct.VIDEO_SAVER.display_name
    'Video Saver'
    >>> PremiumProduct.VIDEO_SAVER.expected_sku_type.name
    'durable'
    """

    VIDEO_SAVER = "video_saver"
    SPOOKY_PREMIUM = "spooky_premium"

    @property
    def display_name(self) -> str:
        """Return a human-readable display name for embeds and logs.

        Returns
        -------
        str
            User-friendly label for this premium product.
        """
        if self is PremiumProduct.SPOOKY_PREMIUM:
            return "Spooky Premium"
        return "Video Saver"

    def aliases(self) -> tuple[str, ...]:
        """Return normalized identifiers that should map to this product.

        Returns
        -------
        tuple[str, ...]
            Canonical aliases used to match SKUs by name during cache
            synchronization.

        Notes
        -----
        - Used internally by :func:`spooky.premium.cache.fill_bot_sku_cache`
          to resolve SKUs by normalized name.
        """
        aliases = [
            self.value,
            self.display_name.lower(),
        ]
        if self is PremiumProduct.SPOOKY_PREMIUM:
            aliases.append("spooky premium monthly")
        return tuple(aliases)

    @property
    def expected_sku_type(self) -> SKUType:
        """Return the expected Discord SKU type for this product.

        Returns
        -------
        SKUType
            SKU type constant from :class:`disnake.SKUType`.

        Notes
        -----
        - This helps validate SKU compatibility when registering or syncing
          products within the developer tooling commands.
        """
        if self is PremiumProduct.SPOOKY_PREMIUM:
            return SKUType.subscription
        return SKUType.durable
