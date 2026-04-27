"""Media search tracking models for TikTok and Instagram features."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = ["UserMediaOptOut", "UserMediaSavedSettings", "UserMediaSearch"]


class UserMediaSearch(Base):
    """Persist a record of media searches executed by a user.

    The TikTok and Instagram integrations surface content by executing search
    queries on behalf of the requesting author. To support auditability and to
    pre-populate UI panels with recent activity, each invocation is captured in
    this table.

    Attributes
    ----------
    id:
        Surrogate primary key for the search event.
    user_id:
        Discord user ID for the author who initiated the search. Indexed for
        quick lookups when rendering the user settings panel.
    platform:
        Target media platform (e.g., ``"tiktok"`` or ``"instagram"``). Indexed to
        enable platform-specific filtering.
    ordinal:
        Per-user sequence number used for history lookups and display ordering.
    query:
        The free-form query string executed against the media provider.
    created_at:
        Timestamp when the search was issued (UTC).
    """

    __tablename__ = "media_user_searches"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "platform",
            "ordinal",
            name="uq_media_user_searches_user_platform_ordinal",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(25), index=True, nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class UserMediaOptOut(Base):
    """Per-user opt-out preferences for media search retention.

    When a user toggles the opt-out control within the settings panel, a row is
    inserted (or updated) in this table. Application logic should respect this
    preference by avoiding storage of additional :class:`UserMediaSearch`
    records for the corresponding user and platform.

    Attributes
    ----------
    id:
        Surrogate primary key.
    user_id:
        Discord user ID expressing the preference. Indexed.
    platform:
        Media platform to which the opt-out applies. ``NULL`` indicates the
        preference spans all platforms.
    opt_out:
        Boolean flag indicating whether tracking is disabled for the scoped
        platform.

    Constraints
    -----------
    - ``UNIQUE (user_id, platform)`` ensures a single preference row per user
      and platform pair.
    """

    __tablename__ = "media_user_opt_out"
    __table_args__ = (UniqueConstraint("user_id", "platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UserMediaSavedSettings(Base):
    """Persist Video Saver configuration flags for a user."""

    __tablename__ = "media_user_saved_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_media_user_saved_settings_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    auto_save: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attach_buttons: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attach_embed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
