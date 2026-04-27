from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TOPIC_CATEGORY_MAP",
    "LoggingEventCategory",
    "LoggingEventType",
    "LoggingGuildEvent",
    "LoggingMemberEvent",
    "LoggingMessageEvent",
    "LoggingModerationCategory",
    "LoggingModerationCommand",
    "LoggingThreadEvent",
    "LoggingTopic",
]


class LoggingTopic(StrEnum):
    """Top-level logging topics available to guilds."""

    EVENTS = "events"
    MODERATION = "moderation"


class LoggingEventCategory(StrEnum):
    """Event groupings under the ``events`` logging topic."""

    MESSAGES = "messages"
    MEMBERS = "members"
    CHANNELS = "channels"
    VOICE = "voice"
    GUILD = "guild"
    AUTOMOD = "automod"


class LoggingModerationCategory(StrEnum):
    """Groupings for moderation command logging."""

    PREFIX = "prefix"
    INTERACTION = "interaction"


class LoggingMessageEvent(StrEnum):
    """Individual message-related events within the Messages category."""

    CREATE = "message_create"
    EDIT = "message_edit"
    DELETE = "message_delete"
    BULK_DELETE = "message_bulk_delete"
    PINS_UPDATE = "message_pins_update"
    REACTION_ADD = "reaction_add"
    REACTION_REMOVE = "reaction_remove"


class LoggingMemberEvent(StrEnum):
    """Individual member-related events within the Members category."""

    JOIN = "member_join"
    LEAVE = "member_leave"
    BAN = "member_ban"
    UNBAN = "member_unban"


class LoggingThreadEvent(StrEnum):
    """Thread-specific events grouped under Channels & Threads."""

    CHANNEL_CREATE = "channel_create"
    CHANNEL_DELETE = "channel_delete"
    CHANNEL_UPDATE = "channel_update"
    THREAD_CREATE = "thread_create"
    THREAD_UPDATE = "thread_update"
    THREAD_DELETE = "thread_delete"


class LoggingGuildEvent(StrEnum):
    """Guild-wide configuration and integration events."""

    VOICE_MOVE = "voice_move"
    VOICE_JOIN = "voice_join"
    VOICE_LEAVE = "voice_leave"
    STREAMING_STATUS = "streaming_status"
    VOICE_STATE_CHANGE = "voice_state_change"
    GUILD_SETTINGS_UPDATE = "guild_settings_update"
    WEBHOOK_UPDATE = "webhook_update"
    INTEGRATIONS_UPDATE = "integrations_update"
    AUTOMOD_ACTION = "automod_action"


class LoggingModerationCommand(StrEnum):
    """Individual moderation commands that can be logged."""

    PREFIX_KICK = "prefix_kick"
    PREFIX_BAN = "prefix_ban"
    PREFIX_UNBAN = "prefix_unban"
    PREFIX_SOFTBAN = "prefix_softban"
    PREFIX_HARDBAN = "prefix_hardban"
    PREFIX_ADD_ROLE = "prefix_add_role"
    PREFIX_REMOVE_ROLE = "prefix_remove_role"
    PREFIX_TIMEOUT = "prefix_timeout"
    PREFIX_UNTIMEOUT = "prefix_untimeout"
    INTERACTION_KICK = "interaction_kick"
    INTERACTION_BAN = "interaction_ban"
    INTERACTION_UNBAN = "interaction_unban"
    INTERACTION_SOFTBAN = "interaction_softban"
    INTERACTION_ADD_ROLE = "interaction_add_role"
    INTERACTION_REMOVE_ROLE = "interaction_remove_role"
    INTERACTION_TIMEOUT = "interaction_timeout"
    INTERACTION_UNTIMEOUT = "interaction_untimeout"


LoggingEventType = (
    LoggingMessageEvent
    | LoggingMemberEvent
    | LoggingThreadEvent
    | LoggingGuildEvent
    | LoggingEventCategory
    | LoggingModerationCategory
    | LoggingModerationCommand
)


TOPIC_CATEGORY_MAP: dict[
    LoggingTopic, tuple[LoggingEventCategory | LoggingModerationCategory, ...]
] = {
    LoggingTopic.EVENTS: (
        LoggingEventCategory.MESSAGES,
        LoggingEventCategory.MEMBERS,
        LoggingEventCategory.CHANNELS,
        LoggingEventCategory.VOICE,
        LoggingEventCategory.GUILD,
        LoggingEventCategory.AUTOMOD,
    ),
    LoggingTopic.MODERATION: (
        LoggingModerationCategory.PREFIX,
        LoggingModerationCategory.INTERACTION,
    ),
}
