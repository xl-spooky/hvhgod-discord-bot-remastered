"""Snipe models: persisted snapshots for deleted/edited content and opt-outs.

This module defines the data model for Spooky's **Snipe** subsystem:
- **Message/Sticker snapshots** (for recently deleted or edited content),
- **Per-user visibility controls** (opt-outs and global opt-out flags).

Design
------
- Each snapshot table stores a **minimal, privacy-minded** subset of metadata
  required to surface snipe commands safely (e.g., author display info and
  content when allowed).
- Snapshots include an application-managed ``expires_at`` timestamp. Helpers
  like :meth:`SnipeMessage.set_expiry` return a retention boundary (defaults
  to **1 day**). A periodic job should prune rows where ``expires_at <= now``.
- Per-scope privacy switches:
  - :class:`UserSnipeOptOut` — per-guild user choice to exclude their content.
  - :class:`UserSnipeOptOutAll` — global (user-wide) opt-out across guilds.

Notes
-----
- These models do **not** enforce retention automatically; callers must set
  ``expires_at`` and a background task should delete expired rows.
- All timestamps use timezone-aware ``DateTime(timezone=True)``.
- Long text fields (content, URLs) use ``Text`` to avoid length constraints.

Examples
--------
Creating a snapshot with 24h retention:

>>> row = SnipeMessage(
...     guild_id=123,
...     guild_name="Spooky HQ",
...     user_id=456,
...     author_display_name="Spooky",
...     author_avatar_url="https://cdn/...",
...     message_content="boo!",
...     channel_id=789,
...     deleted_at=datetime.now(UTC),
...     expires_at=SnipeMessage.set_expiry(days=1),
... )

Respecting opt-outs when querying (pseudo):

>>> # if UserSnipeOptOut exists for (guild_id, user_id) with opt_out=True,
>>> # skip storing or skip returning the user's snapshots for that guild.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...base_models.base import Base

__all__ = [
    "GuildSnipeSettings",
    "SnipeEdit",
    "SnipeMessage",
    "SnipeSticker",
    "UserSnipeOptOut",
    "UserSnipeOptOutAll",
]


class SnipeMessage(Base):
    """Snapshot metadata for a **deleted** message.

    Purpose
    -------
    Persist a minimal record that allows moderators (or permitted users) to
    surface the content and context of a recently deleted message, subject
    to privacy and retention policies.

    Attributes
    ----------
    id:
        Surrogate PK.
    guild_id:
        Discord guild ID (snowflake). Indexed for fast guild scans.
    guild_name:
        Guild name at capture time (non-authoritative; convenience only).
    user_id:
        Author's user ID (snowflake). Indexed to enable user-centric queries.
    author_display_name:
        Display name or username at capture time.
    author_avatar_url:
        Resolved avatar URL at capture time.
    message_content:
        Text content of the deleted message, if present and allowed by policy.
    channel_id:
        Channel ID where the message existed. Indexed for channel snipe lookups.
    deleted_at:
        When the delete event was observed (tz-aware).
    expires_at:
        TTL cutoff for retention (tz-aware). Rows at/after this instant should
        be considered expired by pruning jobs.

    Notes
    -----
    - ``message_content`` may be ``NULL`` (e.g., embeds-only, attachments-only,
      or policy restrictions).
    - This table intentionally does not store attachments or embeds payloads.
    - Retention is **application-managed**; see :meth:`set_expiry`.

    Examples
    --------
    >>> SnipeMessage.set_expiry()           # default 1 day
    >>> SnipeMessage.set_expiry(days=7)     # custom retention
    """

    __tablename__ = "snipe_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    guild_name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_display_name: Mapped[str] = mapped_column(String(100))
    author_avatar_url: Mapped[str] = mapped_column(Text())
    message_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    @classmethod
    def set_expiry(cls, days: int = 1) -> datetime:
        """Compute an expiry timestamp in UTC.

        Parameters
        ----------
        days:
            Number of days from **now** (UTC) to retain this snapshot.

        Returns
        -------
        datetime
            A timezone-aware UTC ``datetime`` representing the expiration
            boundary (``now() + timedelta(days=days)``).

        Notes
        -----
        This does **not** write to the database; callers must assign the
        returned value to ``expires_at`` before flush/commit.
        """
        return datetime.now(UTC) + timedelta(days=days)


class SnipeEdit(Base):
    """Snapshot metadata for an **edited** message.

    Purpose
    -------
    Preserve the before/after text to display diffs for recent edits, subject
    to privacy and retention constraints.

    Attributes
    ----------
    id:
        Surrogate PK.
    guild_id:
        Discord guild ID (snowflake). Indexed.
    guild_name:
        Guild name at capture time.
    user_id:
        Author's user ID (snowflake). Indexed.
    author_display_name:
        Display name or username at capture time.
    author_avatar_url:
        Resolved avatar URL at capture time.
    original_content:
        Message content **before** the edit (nullable; may be absent).
    edited_content:
        Message content **after** the edit (nullable; may be absent).
    channel_id:
        Channel ID where the message exists. Indexed.
    edited_at:
        When the edit event was observed (tz-aware).
    expires_at:
        TTL cutoff for retention (tz-aware).

    Notes
    -----
    - ``original_content`` and ``edited_content`` may be ``NULL`` if content
      was not accessible (e.g., embeds-only) or policy precluded storage.
    - Retention is application-managed; see :meth:`set_expiry`.
    """

    __tablename__ = "snipe_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    guild_name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_display_name: Mapped[str] = mapped_column(String(100))
    author_avatar_url: Mapped[str] = mapped_column(Text())
    original_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    edited_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    @classmethod
    def set_expiry(cls, days: int = 1) -> datetime:
        """Compute an expiry timestamp in UTC.

        Parameters
        ----------
        days:
            Number of days from **now** (UTC) to retain this snapshot.

        Returns
        -------
        datetime
            A timezone-aware UTC ``datetime`` representing the expiration
            boundary (``now() + timedelta(days=days)``).
        """
        return datetime.now(UTC) + timedelta(days=days)


class SnipeSticker(Base):
    """Snapshot metadata for a **deleted sticker** event.

    Purpose
    -------
    Record the basic identity and context for sticker deletions to enable
    moderator visibility and recent-history queries.

    Attributes
    ----------
    id:
        Surrogate PK.
    guild_id:
        Discord guild ID (snowflake). Indexed.
    guild_name:
        Guild name at capture time.
    user_id:
        Author's user ID (snowflake). Indexed.
    author_display_name:
        Display name or username at capture time.
    author_avatar_url:
        Resolved avatar URL at capture time.
    channel_id:
        Channel ID where the sticker was posted. Indexed.
    sticker_name:
        Human-readable sticker name at capture time.
    sticker_url:
        Direct URL for the sticker asset at capture time.
    deleted_at:
        When the delete event was observed (tz-aware).
    expires_at:
        TTL cutoff for retention (tz-aware).

    Notes
    -----
    - The sticker binary is **not** stored; only identifying metadata/URL.
    - Retention is application-managed; see :meth:`set_expiry`.
    """

    __tablename__ = "snipe_stickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    guild_name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_display_name: Mapped[str] = mapped_column(String(100))
    author_avatar_url: Mapped[str] = mapped_column(Text())
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sticker_name: Mapped[str] = mapped_column(String(255))
    sticker_url: Mapped[str] = mapped_column(Text())
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    @classmethod
    def set_expiry(cls, days: int = 1) -> datetime:
        """Compute an expiry timestamp in UTC.

        Parameters
        ----------
        days:
            Number of days from **now** (UTC) to retain this snapshot.

        Returns
        -------
        datetime
            A timezone-aware UTC ``datetime`` representing the expiration
            boundary (``now() + timedelta(days=days)``).
        """
        return datetime.now(UTC) + timedelta(days=days)


class UserSnipeOptOut(Base):
    """Per-guild user **opt-out** for snipe visibility.

    Purpose
    -------
    Allow a user to opt-out of having their deleted/edited content stored
    or displayed within a specific guild.

    Attributes
    ----------
    id:
        Surrogate PK.
    guild_id:
        Guild in which the preference applies. Indexed.
    user_id:
        The opting-out user. Indexed.
    opt_out:
        ``True`` if the user has opted out for this guild.

    Constraints
    -----------
    - ``UNIQUE (guild_id, user_id)`` — one row per user x guild.

    Notes
    -----
    - Enforcement is implemented in application logic (pre-store checks and/or
      query filters).
    """

    __tablename__ = "snipe_opt_out"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserSnipeOptOutAll(Base):
    """Per-user **global** opt-out across guilds.

    Purpose
    -------
    When enabled, this user will not have their content logged or surfaced in
    any guild, regardless of per-guild settings.

    Attributes
    ----------
    id:
        Surrogate PK.
    user_id:
        The opting-out user. Unique and indexed.
    opt_out_all:
        ``True`` if globally opted out from Snipe logging across guilds.

    Notes
    -----
    - This does not prevent guild-local storage or visibility unless combined
      with per-guild :class:`UserSnipeOptOut`.
    """

    __tablename__ = "snipe_opt_out_all"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    opt_out_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GuildSnipeSettings(Base):
    """Per-guild toggle controlling whether Snipe logging is disabled."""

    __tablename__ = "snipe_guild_exclude_all"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    disabled: Mapped[bool] = mapped_column(
        "exclude_from_all", Boolean, nullable=False, default=False
    )
