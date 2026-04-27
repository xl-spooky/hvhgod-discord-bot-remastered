"""SQLAlchemy model and helper re-exports for ergonomic imports.

This module serves as a **consolidated public entry point** for commonly used
Spooky ORM models, enums, cache utilities, and database helper functions.

Instead of importing from multiple submodules such as
``spooky.models.base_models.user``,
``spooky.models.cache`` or
``spooky.models.entities.utility``,
project code can simply import from ``spooky.models`` for cleaner readability
and reduced import clutter.

Contents
--------
- Core ORM base + Discord entity mixins
- User/Guild models
- Snipe models
- Permission + command override models
- Cache utilities for Discord entity resolution
- DB fetch-or-create helpers
- Bulk ensure + model diff helpers
- Enum: ``AppPermission``

Examples
--------
>>> from spooky.models import User, Guild, UserPermissionOverride
>>> from spooky.models import ensure_member, invalidate_role

Notes
-----
- This module does *not* define new logic; it provides a curated export surface.
- Internal modules may still be used for advanced or private use cases.
"""

from .base_models.base import Base, DiscordEntity
from .base_models.guild import Guild
from .base_models.user import User
from .cache import (
    CacheStats,
    TTLCache,
    ensure_channel,
    ensure_emoji,
    ensure_guild,
    ensure_member,
    ensure_role,
    ensure_sticker,
    ensure_user,
    invalidate_channel,
    invalidate_guild,
    invalidate_member,
    invalidate_role,
    invalidate_user,
)
from .entities.auto import AutoChannelNuke
from .entities.bot_settings import (
    GuildCommandDisabled,
    GuildCommandRoleOverride,
    GuildCommandUserOverride,
)
from .entities.logging import (
    TOPIC_CATEGORY_MAP,
    GuildLoggingEventCategorySettings,
    GuildLoggingEventSettings,
    GuildLoggingEventsSettings,
    GuildLoggingModerationSettings,
    GuildLoggingSettings,
    LoggingEventCategory,
    LoggingGuildEvent,
    LoggingMemberEvent,
    LoggingMessageEvent,
    LoggingModerationCategory,
    LoggingModerationCommand,
    LoggingThreadEvent,
    LoggingTopic,
)
from .entities.media import UserMediaOptOut, UserMediaSavedSettings, UserMediaSearch

# Moderation history models (explicit import keeps them registered for migrations).
from .entities.moderation import (
    ModerationAction,
    ModerationActionType,
    ModerationCommandThreshold,
    ModerationCommandUsage,
)
from .entities.owners import (
    AuthorizationAccess,
    GuildBotAuthorizationAccess,
    GuildBotConfigureAuthorization,
)
from .entities.permissions import AppPermission, UserPermissionOverride
from .entities.premium import PremiumEntitlement, PremiumSavedMedia, PremiumSKU
from .entities.utility import (
    GuildSnipeSettings,
    SnipeEdit,
    SnipeMessage,
    SnipeSticker,
    UserSnipeOptOut,
    UserSnipeOptOutAll,
)
from .utils import (
    bulk_ensure_guilds,
    bulk_ensure_users,
    fetch_db_guild,
    fetch_db_user,
    get_model_changes,
)

__all__ = [
    "TOPIC_CATEGORY_MAP",
    "AppPermission",
    "AuthorizationAccess",
    "AutoChannelNuke",
    "Base",
    "CacheStats",
    "DiscordEntity",
    "Guild",
    "GuildBotAuthorizationAccess",
    "GuildBotConfigureAuthorization",
    "GuildCommandDisabled",
    "GuildCommandRoleOverride",
    "GuildCommandUserOverride",
    "GuildLoggingEventCategorySettings",
    "GuildLoggingEventSettings",
    "GuildLoggingEventsSettings",
    "GuildLoggingModerationSettings",
    "GuildLoggingSettings",
    "GuildSnipeSettings",
    "LoggingEventCategory",
    "LoggingGuildEvent",
    "LoggingMemberEvent",
    "LoggingMessageEvent",
    "LoggingModerationCategory",
    "LoggingModerationCommand",
    "LoggingThreadEvent",
    "LoggingTopic",
    "ModerationAction",
    "ModerationActionType",
    "ModerationCommandThreshold",
    "ModerationCommandUsage",
    "PremiumEntitlement",
    "PremiumSKU",
    "PremiumSavedMedia",
    "SnipeEdit",
    "SnipeMessage",
    "SnipeSticker",
    "TTLCache",
    "User",
    "UserMediaOptOut",
    "UserMediaSavedSettings",
    "UserMediaSearch",
    "UserPermissionOverride",
    "UserSnipeOptOut",
    "UserSnipeOptOutAll",
    "bulk_ensure_guilds",
    "bulk_ensure_users",
    "ensure_channel",
    "ensure_emoji",
    "ensure_guild",
    "ensure_member",
    "ensure_role",
    "ensure_sticker",
    "ensure_user",
    "fetch_db_guild",
    "fetch_db_user",
    "get_model_changes",
    "invalidate_channel",
    "invalidate_guild",
    "invalidate_member",
    "invalidate_role",
    "invalidate_user",
]
