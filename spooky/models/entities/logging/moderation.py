"""Logging topic model helpers for Moderation commands."""

from __future__ import annotations

from typing import ClassVar

from .enums import LoggingModerationCategory, LoggingTopic
from .models import GuildLoggingSettings

__all__ = ["GuildLoggingModerationSettings"]


class GuildLoggingModerationSettings(GuildLoggingSettings):
    """Typed view of :class:`GuildLoggingSettings` for the Moderation topic."""

    __tablename__ = None
    topic_key: ClassVar[str] = LoggingTopic.MODERATION.value
    category_keys: ClassVar[tuple[str, ...]] = tuple(
        category.value for category in LoggingModerationCategory
    )

    def __init__(
        self,
        *,
        guild_id: int,
        channel_id: int | None = None,
        webhook_id: int | None = None,
        enabled: bool = False,
    ) -> None:
        super().__init__(
            guild_id=guild_id,
            topic=self.topic_key,
            channel_id=channel_id,
            webhook_id=webhook_id,
            enabled=enabled,
        )
