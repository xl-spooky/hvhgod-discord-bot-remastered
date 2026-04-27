"""Database error helpers.

Centralizes detection of recurring database exception patterns so callers can
avoid duplicating checks across listeners and command handlers.
"""

from __future__ import annotations

from asyncpg import TooManyConnectionsError
from loguru import logger
from sqlalchemy.exc import DBAPIError

__all__ = ["handle_db_capacity_error", "is_db_capacity_error"]


def _unwrap_dbapi(error: BaseException) -> BaseException:
    """Return the underlying DBAPI error if present."""
    if isinstance(error, DBAPIError):
        orig = getattr(error, "orig", None)
        if isinstance(orig, BaseException):
            return orig
    return error


def is_db_capacity_error(error: BaseException) -> bool:
    """Return ``True`` when ``error`` indicates database connection saturation."""
    root = _unwrap_dbapi(error)
    return isinstance(root, TooManyConnectionsError)


def handle_db_capacity_error(error: BaseException, *, context: str | None = None) -> bool:
    """Log and classify TooManyConnections as a capacity event.

    Returns ``True`` if handled so callers can skip further processing.
    """
    if not is_db_capacity_error(error):
        return False

    if context:
        logger.info("Database at capacity during {}; deferring", context)
    else:
        logger.info("Database at capacity; deferring")
    return True
