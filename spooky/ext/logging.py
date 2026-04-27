"""Helpers for querying logging topics dynamically.

These helpers provide a single entry point to check whether a logging topic is
currently enabled for a guild. Topics can be passed by name (``"events"``), by a
model that exposes ``topic_key`` (e.g., :class:`~spooky.models.GuildLoggingEventsSettings`),
or by a struct with a ``key`` attribute (such as
:class:`~spooky.bot.extensions.settings.guild.containers.logs.types.LoggingTopicDefinition`).

Example
-------
>>> await logging_topic_enabled(123, "events")
True
>>> await logging_topic_enabled(123, GuildLoggingEventsSettings)
True
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from spooky.core import settings
from spooky.ext.db import fetch_bool_flag
from spooky.ext.http import HttpClient
from spooky.models import (
    GuildLoggingEventCategorySettings,
    GuildLoggingEventSettings,
    GuildLoggingSettings,
)

__all__ = [
    "logging_category_enabled",
    "logging_event_enabled",
    "logging_topic_enabled",
    "post_logging_webhook",
]


class TopicKeyCarrier(Protocol):
    """Protocol for objects exposing a ``key`` attribute."""

    key: str


class TopicKeyProvider(Protocol):
    """Protocol for objects exposing a ``topic_key`` attribute."""

    topic_key: str


TopicInput = str | TopicKeyProvider | TopicKeyCarrier


def _topic_key(topic: TopicInput) -> str:
    if isinstance(topic, str):
        return topic

    topic_key = getattr(topic, "topic_key", None)
    if isinstance(topic_key, str):
        return topic_key

    key = getattr(topic, "key", None)
    if isinstance(key, str):
        return key

    return str(topic)


async def logging_topic_enabled(guild_id: int, topic: TopicInput, *, default: bool = False) -> bool:
    """Return ``True`` when ``topic`` is enabled for ``guild_id``.

    Parameters
    ----------
    guild_id : int
        Target guild ID.
    topic : TopicInput
        Logging topic identifier. Accepts a string, a class/instance exposing
        ``topic_key``, or any object with a ``key`` attribute.
    default : bool, optional
        Value returned when the topic row is missing or a query error occurs.

    Returns
    -------
    bool
        ``True`` if the topic is marked enabled in the database; otherwise
        ``default``.
    """
    topic_key = _topic_key(topic)
    return await fetch_bool_flag(
        GuildLoggingSettings.filter(guild_id=guild_id, topic=topic_key),
        field="enabled",
        default=default,
    )


async def logging_category_enabled(
    guild_id: int,
    topic: TopicInput,
    category: str,
    *,
    default: bool = False,
) -> bool:
    """Return ``True`` when a logging sub-category is enabled for ``topic``.

    Parameters
    ----------
    guild_id : int
        Target guild ID.
    topic : TopicInput
        Logging topic identifier. Accepts a string, a class/instance exposing
        ``topic_key``, or any object with a ``key`` attribute.
    category : str
        Sub-category name (e.g., ``"messages"``) to evaluate.
    default : bool, optional
        Value returned when the category row is missing or a query error occurs.

    Returns
    -------
    bool
        ``True`` if the category row exists and is enabled; otherwise
        ``default``.
    """
    topic_key = _topic_key(topic)
    return await fetch_bool_flag(
        GuildLoggingEventCategorySettings.filter(
            guild_id=guild_id, topic=topic_key, category=category
        ),
        field="enabled",
        default=default,
    )


async def logging_event_enabled(
    guild_id: int,
    topic: TopicInput,
    category: str,
    event: str,
    *,
    default: bool = True,
) -> bool:
    """Return ``True`` when a specific logging event is enabled for ``category``.

    Parameters
    ----------
    guild_id : int
        Target guild ID.
    topic : TopicInput
        Logging topic identifier. Accepts a string, a class/instance exposing
        ``topic_key``, or any object with a ``key`` attribute.
    category : str
        Category name (e.g., ``"messages"``) to evaluate.
    event : str
        Event name (e.g., ``"message_create"``) to evaluate.
    default : bool, optional
        Value returned when the event row is missing or a query error occurs.

    Returns
    -------
    bool
        ``True`` if the event row exists and is enabled; otherwise ``default``.
    """
    topic_key = _topic_key(topic)
    return await fetch_bool_flag(
        GuildLoggingEventSettings.filter(
            guild_id=guild_id, topic=topic_key, category=category, event=event
        ),
        field="enabled",
        default=default,
    )


async def post_logging_webhook(
    guild_id: int,
    topic: TopicInput,
    payload: Mapping[str, Any],
    /,
) -> bool:
    """Send ``payload`` to the webhook configured for ``topic`` in ``guild_id``.

    This helper resolves the stored webhook ID for the topic, fetches the webhook
    token via Discord's API using the shared :class:`~spooky.ext.http.HttpClient`,
    and posts the payload to the webhook endpoint.

    Parameters
    ----------
    guild_id : int
        Target guild ID.
    topic : TopicInput
        Logging topic identifier. Accepts a string, a class/instance exposing
        ``topic_key``, or any object with a ``key`` attribute.
    payload : Mapping[str, Any]
        JSON-compatible body sent to the webhook.

    Returns
    -------
    bool
        ``True`` when the webhook exists and accepts the payload; ``False`` for
        missing configuration or HTTP errors.
    """
    topic_key = _topic_key(topic)
    webhook_ids = await GuildLoggingSettings.filter(guild_id=guild_id, topic=topic_key).values_list(
        "webhook_id", flat=True
    )

    if not webhook_ids:
        return False

    webhook_id = webhook_ids[0]
    if webhook_id is None:
        return False

    headers = {"Authorization": f"Bot {settings.bot.token}"}
    try:
        async with HttpClient.session.get(
            f"https://discord.com/api/v10/webhooks/{webhook_id}", headers=headers
        ) as response:
            response.raise_for_status()
            webhook = await response.json()
    except Exception:
        return False

    token = webhook.get("token") if isinstance(webhook, Mapping) else None
    if not isinstance(token, str):
        return False

    try:
        async with HttpClient.session.post(
            f"https://discord.com/api/v10/webhooks/{webhook_id}/{token}",
            json=dict(payload),
        ) as response:
            response.raise_for_status()
    except Exception:
        return False

    return True
