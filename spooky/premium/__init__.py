"""Public API surface for the Premium package.

This package-level module centralizes re-exports intended for external
consumers. Importing from :mod:`spooky.premium` provides a stable entry point
for premium-related types without exposing internal module layout.

Usage
-----
Prefer importing from the package root for forward compatibility::

    from spooky.premium import PremiumProduct

Notes
-----
- The root export mirrors :mod:`spooky.premium.enums` to decouple callers from
  internal file structure.
- Add new public types here to avoid breaking downstream imports when
  reorganizing modules.
"""

from __future__ import annotations

from .enums import PremiumProduct

__all__ = ["PremiumProduct"]
