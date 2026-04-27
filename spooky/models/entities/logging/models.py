from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base


class GuildLoggingSettings(Base):
    """Persist logging destinations and webhooks per guild/topic."""

    __tablename__ = "guild_logging_settings"
    __table_args__ = (UniqueConstraint("guild_id", "topic", name="uq_logging_topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    topic: Mapped[str] = mapped_column(String(50))
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    webhook_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class GuildLoggingEventCategorySettings(Base):
    """Per-topic sub-category toggles for guild logging."""

    __tablename__ = "guild_logging_event_categories"
    __table_args__ = (
        UniqueConstraint("guild_id", "topic", "category", name="uq_logging_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    topic: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class GuildLoggingEventSettings(Base):
    """Per-event toggles for granular logging configuration."""

    __tablename__ = "guild_logging_events"
    __table_args__ = (
        UniqueConstraint("guild_id", "topic", "category", "event", name="uq_logging_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    topic: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(50))
    event: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


__all__ = [
    "GuildLoggingEventCategorySettings",
    "GuildLoggingEventSettings",
    "GuildLoggingSettings",
]
