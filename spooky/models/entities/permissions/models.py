from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = ["UserPermissionOverride"]


class UserPermissionOverride(Base):
    """Per-guild user override of internal application permissions."""

    __tablename__ = "user_permission_overrides"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "perm_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    perm_name: Mapped[str] = mapped_column(String(64))
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
