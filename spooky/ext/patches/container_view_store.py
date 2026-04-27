"""Compat patch for ``disnake`` view storage to unwrap container payloads.

This module installs a small, **idempotent monkey-patch** to
``disnake.ui.view.ViewStore.update_from_message`` so that it ignores
"container" wrappers introduced by higher-level UI abstractions (e.g. a
virtual container that groups multiple action rows). The patch flattens such
containers into plain action row payloads before delegating to the original
implementation.

Why this exists
---------------
Some UI layers produce a component shape like:

- Top-level **container** (custom logical wrapper)
  - One or more **action_row** payloads (valid Discord components)

The stock ``ViewStore`` expects **action rows** at the top level. Without
flattening, it would treat the container as an unknown/invalid component
shape when hydrating views from message payloads.

Usage
-----
Call :func:`apply_container_view_store_patch` once during startup (e.g. in
your bot bootstrap) **before** receiving interaction payloads.

Notes
-----
- The patch is **idempotent** and guarded by a marker attribute on the
  patched function; repeated calls are safe.
- No behavior changes occur unless a container wrapper is detected; other
  payloads pass through unchanged.
- The patch keeps the original function object around and delegates to it
  after flattening.

"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias, cast

from disnake.enums import ComponentType
from disnake.ui.view import ViewStore

__all__ = ["apply_container_view_store_patch"]

#: JSON-like mapping for a single component payload as received from the API.
ComponentPayload: TypeAlias = Mapping[str, Any]
#: Sequence of component payloads or implementation-specific objects.
ComponentSequence: TypeAlias = Sequence[ComponentPayload | Any]


def _flatten_container_payloads(components: ComponentSequence) -> list[ComponentPayload | Any]:
    """Return a list of component payloads without container wrappers.

    This helper scans the incoming component sequence and unwraps any
    **container** payloads by lifting their **action_row** children to the
    top level. Non-mapping entries (implementation artifacts) and ordinary
    mappings are preserved as-is.

    Parameters
    ----------
    components
        Sequence of component payloads (mappings) or implementation-specific
        objects produced by the UI layer.

    Returns
    -------
    list[ComponentPayload | Any]
        New list where any container wrappers have been replaced by their
        action row children. Entries that were not containers are preserved.

    Notes
    -----
    - Only payloads whose ``type`` matches :class:`~disnake.enums.ComponentType.container`
      are unwrapped. Children are included **only** if they are mappings with
      ``type == ComponentType.action_row.value``.
    - This function is **pure** with respect to the input sequence; it never
      mutates the provided objects and instead builds a new list.

    """
    flattened: list[ComponentPayload | Any] = []
    for payload in components:
        if isinstance(payload, Mapping):
            mapping_payload = cast(ComponentPayload, payload)
            if mapping_payload.get("type") == ComponentType.container.value:
                children = mapping_payload.get("components")
                if isinstance(children, Sequence):
                    for child in children:
                        if (
                            isinstance(child, Mapping)
                            and child.get("type") == ComponentType.action_row.value
                        ):
                            flattened.append(cast(ComponentPayload, child))
                # Skip appending the container itself.
                continue
            # Non-container mapping: keep as-is.
            flattened.append(mapping_payload)
            continue
        # Non-mapping sentinel/object: keep as-is.
        flattened.append(payload)
    return flattened


def apply_container_view_store_patch() -> None:
    """Patch ``ViewStore.update_from_message`` to ignore container wrappers.

    Installs an idempotent wrapper around
    :meth:`disnake.ui.view.ViewStore.update_from_message` that first calls
    :func:`_flatten_container_payloads` and then delegates to the original
    implementation.

    Behavior
    --------
    - If a prior invocation already applied the patch, this function returns
      immediately (no-op).
    - The original method reference is captured once and reused for all calls
      through the patched wrapper.
    - The wrapper sets a marker attribute ``__spooky_container_patch__ = True``
      to indicate that the patch is installed.

    Raises
    ------
    None
        This function performs a safe monkey-patch and will silently no-op if
        already applied.

    Examples
    --------
    >>> # During bot startup:
    >>> from spooky.ext.components.patches import apply_container_view_store_patch
    >>> apply_container_view_store_patch()

    """
    if getattr(ViewStore.update_from_message, "__spooky_container_patch__", False):
        return

    original = ViewStore.update_from_message

    def update_from_message(
        self: ViewStore, message_id: int, components: ComponentSequence
    ) -> None:
        flattened = _flatten_container_payloads(components)
        # ``original`` expects a sequence of component payloads; after flattening,
        # the shape matches the stock expectations.
        return original(self, message_id, flattened)  # type: ignore[arg-type]

    setattr(update_from_message, "__spooky_container_patch__", True)
    ViewStore.update_from_message = update_from_message  # type: ignore[assignment]
