"""Auto-action models for scheduled channel nuking."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = ["AutoChannelNuke"]


class AutoChannelNuke(Base):
    """Schedule automatic channel nukes for a guild."""

    __tablename__ = "auto_channel_nukes"
    __table_args__ = (UniqueConstraint("guild_id", "channel_id", name="uq_auto_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    nuke_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
