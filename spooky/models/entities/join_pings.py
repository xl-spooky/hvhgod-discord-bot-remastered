"""Join-ping configuration persistence models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base_models.base import Base


class JoinPingConfig(Base):
    """Persist channels/threads where newcomer ping messages should be emitted."""

    __tablename__ = "join_ping_configs"
    __table_args__ = (UniqueConstraint("guild_id", "channel_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
