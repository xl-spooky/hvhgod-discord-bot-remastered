"""Version 2 component helpers (views, cards, pagination, etc.).

This package collects reusable V2 UI primitives used throughout the
application, including:

Exports
-------
BaseView
    A foundational view class providing structured lifecycle behavior.
PaginationView
    A pageable UI controller supporting multi-page display logic.
status_card
    Convenience helper for returning standardized success/failure embeds.
CardPalette
    A style palette used internally by card builders.

Purpose
-------
By re-exporting these key components here, consumers can conveniently import
V2 UI helpers from a central location rather than targeting submodules.
"""

from __future__ import annotations

from .base_view import BaseView
from .card import CardPalette, status_card
from .confirmation import ConfirmationView
from .pagination import PaginationView

__all__ = ["BaseView", "CardPalette", "ConfirmationView", "PaginationView", "status_card"]
