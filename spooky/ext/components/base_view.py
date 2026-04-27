"""Compatibility wrapper for :mod:`spooky.ext.components.v2.base_view`.

This module re-exports :class:`BaseView` from the v2 component namespace to
preserve backwards compatibility for extensions still importing it from the
current location.

Intended Usage
--------------
Legacy code can continue importing:

>>> from spooky.ext.components.base_view import BaseView

while newer implementations should prefer:

>>> from spooky.ext.components.v2.base_view import BaseView

Once all dependents migrate to the v2 path, this wrapper may be deprecated
and subsequently removed.
"""

from __future__ import annotations

from spooky.ext.components.v2.base_view import BaseView

__all__ = ["BaseView"]
