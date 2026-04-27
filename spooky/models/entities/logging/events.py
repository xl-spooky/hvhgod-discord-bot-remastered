"""Logging topic model helpers for the Events stream."""

from __future__ import annotations

from typing import ClassVar

from .enums import LoggingEventCategory, LoggingTopic
from .models import GuildLoggingSettings

__all__ = ["GuildLoggingEventsSettings"]


class GuildLoggingEventsSettings(GuildLoggingSettings):
    """Typed view of :class:`GuildLoggingSettings` for the Events topic.

    This subclass reuses the base logging table but fixes the ``topic``
    field to ``"events"`` so callers can reference a dedicated model for
    Events logging without repeating the topic key.
    """

    __tablename__ = None  # reuse ``guild_logging_settings`` table
    topic_key: ClassVar[str] = LoggingTopic.EVENTS.value
    category_keys: ClassVar[tuple[str, ...]] = tuple(
        category.value for category in LoggingEventCategory
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
