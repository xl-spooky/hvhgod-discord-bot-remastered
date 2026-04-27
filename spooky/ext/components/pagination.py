"""Compatibility wrapper for :mod:`spooky.ext.components.v2.pagination`.

This module re-exports :class:`PaginationView` from the v2 component namespace
to preserve backwards compatibility for extensions still importing it from the
current location.

Intended Usage
--------------
Legacy code can continue importing:

>>> from spooky.ext.components.pagination import PaginationView

while newer implementations should prefer:

>>> from spooky.ext.components.v2.pagination import PaginationView

Once all dependents migrate to the v2 path, this wrapper may be deprecated
and eventually removed.
"""

from __future__ import annotations

from spooky.ext.components.v2.pagination import PaginationView

__all__ = ["PaginationView"]
