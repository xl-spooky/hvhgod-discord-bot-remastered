"""Runtime patches for third-party libraries (idempotent re-exports).

This module centralizes **monkey-patches** applied at runtime to external
dependencies used by the Spooky/Bail ecosystem. Importing this module does
*not* apply any patches by itself; instead, it **re-exports** callable
patch installers that you should invoke explicitly during application
bootstrap.

Design
------
- Keep each patch in its own focused module (e.g., ``.container_view_store``).
- Re-export patch functions here for a single, stable import surface.
- Patches are **idempotent** and safe to call multiple times; each installer
  guards itself to avoid re-applying the same mutation.

Usage
-----
Call the desired patch function once at startup, before handling events:

>>> from spooky.ext.components.patches import apply_container_view_store_patch
>>> apply_container_view_store_patch()

Available patches
-----------------
- :func:`apply_container_view_store_patch`: unwraps container components
  before delegating to ``disnake.ui.view.ViewStore.update_from_message``.

"""

from __future__ import annotations

from .container_view_store import apply_container_view_store_patch

__all__ = ["apply_container_view_store_patch"]
