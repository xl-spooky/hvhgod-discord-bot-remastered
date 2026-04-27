"""Models for moderation command threshold limits and usage."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = ["ModerationCommandThreshold", "ModerationCommandUsage"]


class ModerationCommandThreshold(Base):
    """Per-target threshold limits for moderation actions within a guild.

    Thresholds are scoped to a guild and either a **user** or **role** target
    and define the maximum number of moderation actions that can be executed in
    a rolling time window. They are resolved in the following priority order:

    1. Explicit **user** threshold (highest priority).
    2. First matching **role** threshold for any of the member's roles.

    Thresholds are stored **per command** so that each moderation action can be
    tuned independently.

    Attributes
    ----------
    id:
        Surrogate primary key.
    guild_id:
        Discord guild snowflake. Indexed for lookups.
    target_id:
        Discord user or role snowflake, depending on ``target_type``.
    target_type:
        Either ``"user"`` or ``"role"``.
    command_name:
        Fully-qualified command identifier prefixed with invocation type, e.g.,
        ``"interaction:ban"`` or ``"prefix:timeout"``.
    max_actions:
        Maximum number of moderation actions allowed within ``window_seconds``.
    window_seconds:
        Sliding window, in seconds, over which ``max_actions`` is enforced.
    created_at:
        Timestamp indicating when the threshold row was created.
    """

    __tablename__ = "moderation_command_threshold"
    __table_args__ = (UniqueConstraint("guild_id", "target_id", "target_type", "command_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_type: Mapped[str] = mapped_column(String(8), index=True)
    command_name: Mapped[str] = mapped_column(String(64), index=True)
    max_actions: Mapped[int] = mapped_column(Integer)
    window_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModerationCommandUsage(Base):
    """Track moderation command usage for threshold enforcement."""

    __tablename__ = "moderation_command_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    moderator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_type: Mapped[str] = mapped_column(String(8), index=True)
    command_name: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
