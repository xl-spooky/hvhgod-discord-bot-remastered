"""Utilities for collecting command data and building help containers.

This module bridges raw command metadata gathered from the bot into **renderable
containers** for the message-based Help UI. It provides:

- Discovery & categorization via :func:`collect_help_entries`
- Container assembly for the overview and per-command pages via
  :func:`build_help_menu`
- Formatting helpers for usage lines, arguments, summaries, and examples
- Prefix resolution that gracefully handles strings and iterables

Design notes
------------
- We rely on :func:`spooky.bot.command_loader.get_all_command_data` to produce a
  normalized, serializable view of both **message** and **interaction** commands.
- Output is structured with dataclasses from :mod:`.models` to decouple data
  collection from UI rendering.
- Containers are built once per menu render to avoid recomputing layout while
  users paginate or change categories.

Constants
---------
- :data:`DEFAULT_CATEGORY` — Fallback grouping when a command lacks an explicit
  ``extras["category"]``.
- :data:`_MAX_OPTION_LABEL_LENGTH` — Upper bound for select option labels.
- :data:`_MAX_DESCRIPTION_LENGTH` — Soft cap for category/command descriptions in lists.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import disnake
from disnake import ui
from spooky.bot import Spooky
from spooky.bot.command_loader import CommandData, CommandParameterData, get_all_command_data
from spooky.core import colors
from spooky.ext.truncate import truncate

from .models import HelpCategory, HelpCommand, HelpEntry, HelpMenu, HelpTopicResolution

__all__ = [
    "DEFAULT_CATEGORY",
    "build_help_menu",
    "collect_help_entries",
    "resolve_help_topic",
    "resolve_prefix",
]

DEFAULT_CATEGORY = "General"
"""Fallback category label used when a command provides no explicit ``extras['category']``."""

_MAX_OPTION_LABEL_LENGTH = 100
"""Maximum number of characters to allow for select option labels."""

_MAX_DESCRIPTION_LENGTH = 100
"""Soft truncation limit for summaries/descriptions shown in lists."""

_HELP_TOPIC_EXTRA_KEY = "help_topics"
"""Command extra key used to declare custom help topic slugs."""


def _default_category_counts() -> dict[str, int]:
    """Return a zeroed count map for prefix and interaction commands.

    Returns
    -------
    dict[str, int]
        Mapping with keys ``"message"`` and ``"interaction"`` initialized to ``0``.
    """
    return {"message": 0, "interaction": 0}


def resolve_prefix(raw_prefix: object, fallback: str) -> str:
    """Return a usable prefix string for displaying prefixed commands.

    Accepts either a single string or an iterable of strings (e.g. results from
    :func:`disnake.ext.commands.when_mentioned_or`). When an iterable is provided,
    the first **non-mention** candidate (not starting with ``"<@"``) is preferred.

    Parameters
    ----------
    raw_prefix : object
        A string, or an iterable of candidate strings, from which to derive an
        effective display prefix.
    fallback : str
        Value to return when no valid prefix can be derived from ``raw_prefix``.

    Returns
    -------
    str
        Effective display prefix, trimmed of surrounding whitespace.
    """
    if isinstance(raw_prefix, str) and raw_prefix.strip():
        return raw_prefix.strip()

    if isinstance(raw_prefix, Iterable) and not isinstance(raw_prefix, (str, bytes)):
        for candidate in raw_prefix:
            if isinstance(candidate, str) and candidate.strip() and not candidate.startswith("<@"):
                return candidate.strip()
        for candidate in raw_prefix:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    return fallback


def collect_help_entries(bot: Spooky) -> list[HelpEntry]:
    """Collect and categorize commands into :class:`HelpEntry` records.

    Performs a deduplicated traversal over both message and interaction commands,
    assigning each to a category derived from ``command.extras['category']`` or
    falling back to :data:`DEFAULT_CATEGORY`. Sorting is stable and groups
    categories alphabetically, with message commands listed before interactions.

    Parameters
    ----------
    bot : Spooky
        The active bot instance used to enumerate registered commands.

    Returns
    -------
    list[HelpEntry]
        Categorized command entries suitable for later rendering.
    """
    entries: list[HelpEntry] = []
    seen: set[tuple[str, str]] = set()

    for command in get_all_command_data(bot):
        if command.type not in {"message", "interaction"}:
            continue
        normalized = command.qualified_name.strip().lower()
        if not normalized:
            continue
        key = (command.type, normalized)
        if key in seen:
            continue
        seen.add(key)

        category = str((command.extras or {}).get("category") or DEFAULT_CATEGORY)
        entries.append(HelpEntry(category=category, command=command))

    entries.sort(
        key=lambda entry: (
            entry.category.lower(),
            0 if entry.command.type == "message" else 1,
            entry.command.qualified_name.lower(),
        )
    )
    return entries


def build_help_menu(bot: Spooky, prefix: str) -> HelpMenu:
    """Build the complete :class:`HelpMenu` (overview + per-category containers).

    Parameters
    ----------
    bot : Spooky
        The active bot instance.
    prefix : str
        Display prefix (e.g., ``","``) used when rendering message command labels,
        usage strings, and examples.

    Returns
    -------
    HelpMenu
        Aggregated data plus prebuilt containers for the overview and categories.

    See Also
    --------
    collect_help_entries : Produces the categorized list of :class:`HelpEntry`.
    """
    entries = collect_help_entries(bot)

    category_entries: dict[str, list[HelpEntry]] = defaultdict(list)
    category_counts: dict[str, dict[str, int]] = defaultdict(_default_category_counts)
    child_map: dict[str, list[CommandData]] = defaultdict(list)
    for entry in entries:
        category_entries[entry.category].append(entry)
        category_counts[entry.category][entry.command.type] += 1
        parent = _parent_qualified_name(entry.command.qualified_name)
        if parent:
            child_map[parent].append(entry.command)

    categories: list[HelpCategory] = []
    topic_map: dict[str, tuple[str | None, str | None]] = {"overview": (None, None)}
    topic_command_map: dict[str, list[str]] = defaultdict(list)
    for index, category in enumerate(sorted(category_entries, key=str.lower)):
        commands: list[HelpCommand] = []
        category_key = _category_key(index, category)
        for entry in category_entries[category]:
            command = entry.command
            command_key = _command_key(command)
            children = child_map.get(command.qualified_name, [])
            command_topics = _command_topics(command)
            child_keys = tuple(_command_key(child) for child in children)
            commands.append(
                HelpCommand(
                    key=command_key,
                    label=_command_label(command, prefix),
                    description=_truncate_description(_command_summary(command)),
                    container=_build_command_container(entry, prefix, children),
                    topics=command_topics,
                    hidden=command.hidden,
                )
            )
            for topic in command_topics:
                topic_map.setdefault(topic, (category_key, command_key))
                _register_topic_command(topic_command_map, topic, command_key)
                for child_key in child_keys:
                    _register_topic_command(topic_command_map, topic, child_key)

        counts = category_counts[category]
        category_topics = _category_topics(category)
        for topic in category_topics:
            topic_map.setdefault(topic, (category_key, None))
            matching_keys = [command.key for command in commands if topic in command.topics]
            if matching_keys:
                for key in matching_keys:
                    _register_topic_command(topic_command_map, topic, key)
            else:
                for command in commands:
                    _register_topic_command(topic_command_map, topic, command.key)
        categories.append(
            HelpCategory(
                key=category_key,
                label=_format_category_label(category),
                description=_format_category_description(counts["message"], counts["interaction"]),
                commands=commands,
                topics=category_topics,
            )
        )

    overview = _build_overview_container(prefix, total_commands=len(entries), categories=categories)
    return HelpMenu(
        overview=overview,
        categories=categories,
        total_commands=len(entries),
        topic_map=topic_map,
        topic_commands={topic: tuple(keys) for topic, keys in topic_command_map.items()},
    )


def _build_overview_container(
    prefix: str,
    *,
    total_commands: int,
    categories: list[HelpCategory],
) -> ui.Container:
    """Return the overview container (legend, categories, and counts).

    Parameters
    ----------
    prefix : str
        Effective message prefix to show in examples (e.g., ``","``).
    total_commands : int
        Total number of discovered commands across all categories.
    categories : list[HelpCategory]
        Help categories used to populate the "Available categories" list.

    Returns
    -------
    disnake.ui.Container
        A container with a short guide, syntax legend, category listing, and
        command count summary.
    """
    summary_lines: list[Any] = [
        ui.TextDisplay("**Help centre**"),
        ui.TextDisplay(
            "Browse commands by picking a category below. Switch categories at any time to "
            "update the command list."
        ),
        ui.Separator(),
        ui.TextDisplay("**Syntax legend**"),
        ui.TextDisplay("• `<required>` — you must supply the option."),
        ui.TextDisplay("• `[optional]` — you can omit the option."),
        ui.Separator(),
        ui.TextDisplay("**Command types**"),
        ui.TextDisplay(f"• Prefix commands use `{prefix}` (e.g., `{prefix}help`)."),
        ui.TextDisplay("• Interaction commands start with `/` in Discord's slash UI."),
        ui.Separator(),
        ui.TextDisplay("**Example usage**"),
        ui.TextDisplay(f"```\n{prefix}command <required> [optional]\n```"),
    ]

    if categories:
        summary_lines.extend(
            [
                ui.Separator(),
                ui.TextDisplay("**Available categories**"),
            ]
        )
        for category in categories:
            description = category.description or "No registered commands."
            summary_lines.append(ui.TextDisplay(f"• **{category.label}** — {description}"))

    summary_lines.extend(
        [
            ui.Separator(),
            ui.TextDisplay(
                f"{total_commands} command{'s' if total_commands != 1 else ''} discovered. "
                "Pick one from the list to see details and an example."
            ),
        ]
    )

    return ui.Container(
        *summary_lines,
        accent_colour=disnake.Colour(colors.embed),
    )


def _register_topic_command(store: dict[str, list[str]], topic: str, command_key: str) -> None:
    """Record ``command_key`` under ``topic`` if it has not been seen."""
    keys = store[topic]
    if command_key not in keys:
        keys.append(command_key)


def _format_category_label(category: str) -> str:
    """Trim a category label to :data:`_MAX_OPTION_LABEL_LENGTH`.

    Parameters
    ----------
    category : str
        Human-readable category label.

    Returns
    -------
    str
        Category label, truncated if necessary.
    """
    return truncate(category, _MAX_OPTION_LABEL_LENGTH)


def _category_key(index: int, category: str) -> str:
    """Generate a stable key for a category option.

    The key encodes the ordinal position and a slugified version of ``category``.

    Parameters
    ----------
    index : int
        Category index in the sorted order.
    category : str
        Human-readable category label.

    Returns
    -------
    str
        Unique, stable key (e.g., ``"category:0:general"``).
    """
    slug = "".join(ch for ch in category.lower() if ch.isalnum() or ch in {"-", "_", " "}).strip()
    slug = slug.replace(" ", "-") or "category"
    return f"category:{index}:{slug}"


def _command_key(command: CommandData) -> str:
    """Generate a stable key for a command entry.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.

    Returns
    -------
    str
        Type-qualified key in the form ``"<type>:<qualified_name>"``.
    """
    return f"{command.type}:{command.qualified_name.lower()}"


def resolve_help_topic(menu: HelpMenu, query: str) -> HelpTopicResolution | None:
    """Return the help menu selection that matches ``query``, if any.

    Parameters
    ----------
    menu : HelpMenu
        The constructed help menu containing topic metadata.
    query : str
        Raw user-provided text following ``",help``.

    Returns
    -------
    HelpTopicResolution | None
        Resolution metadata containing the category/command keys associated with
        ``query`` and the command pool to focus, or ``None`` when no match is
        found.
    """
    normalized = _normalize_topic(query)
    if not normalized:
        return None

    location = menu.topic_map.get(normalized)
    if location is None:
        return None

    category_key, command_key = location
    command_keys = menu.topic_commands.get(normalized, ())
    if command_key is not None and command_key not in command_keys:
        remaining = tuple(key for key in command_keys if key != command_key)
        command_keys = (command_key, *remaining)

    return HelpTopicResolution(
        category_key=category_key,
        command_key=command_key,
        command_keys=command_keys,
    )


def _format_category_description(prefix_count: int, interaction_count: int) -> str:
    """Summarize a category's command counts.

    Parameters
    ----------
    prefix_count : int
        Number of message (prefix) commands in the category.
    interaction_count : int
        Number of interaction (slash) commands in the category.

    Returns
    -------
    str
        A succinct summary like ``"3 prefix commands • 7 interaction commands"``.
    """
    prefix_label = "prefix command" if prefix_count == 1 else "prefix commands"
    interaction_label = "interaction command" if interaction_count == 1 else "interaction commands"
    return f"{prefix_count} {prefix_label} • {interaction_count} {interaction_label}"


def _command_label(command: CommandData, prefix: str) -> str:
    """Return a human-readable label for a command.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.
    prefix : str
        Effective display prefix for message commands.

    Returns
    -------
    str
        Slash-style label (e.g., ``"/config set"``) for interactions or
        prefixed label (e.g., ``",help"``) for message commands.
    """
    if command.type == "interaction":
        return f"/{command.qualified_name}"
    return f"{prefix}{command.qualified_name}"


def _command_topics(command: CommandData) -> tuple[str, ...]:
    """Return normalized topic slugs associated with ``command``."""
    topics: set[str] = set()
    topics.add(_normalize_topic(command.qualified_name))
    topics.add(_normalize_topic(command.name))

    extras = command.extras or {}
    raw_topics = extras.get(_HELP_TOPIC_EXTRA_KEY)
    for topic in _iter_topics(raw_topics):
        normalized = _normalize_topic(topic)
        if normalized:
            topics.add(normalized)

    legacy_topic = extras.get("topic")
    for topic in _iter_topics(legacy_topic):
        normalized = _normalize_topic(topic)
        if normalized:
            topics.add(normalized)

    topics.discard("")
    return tuple(sorted(topics))


def _category_topics(label: str) -> tuple[str, ...]:
    """Return normalized topic slugs associated with a category label."""
    normalized = _normalize_topic(label)
    return (normalized,) if normalized else ()


def _iter_topics(raw: Any) -> tuple[str, ...]:
    """Return topic strings derived from extras values."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        return tuple(str(item) for item in raw if isinstance(item, str) and item.strip())
    return ()


def _normalize_topic(value: str) -> str:
    """Normalize a help topic for consistent lookups."""
    return " ".join(value.lower().split()) if value else ""


def _parent_qualified_name(qualified_name: str) -> str:
    """Return the parent group's qualified name for a slash command, if any.

    Parameters
    ----------
    qualified_name : str
        Fully qualified command name (e.g., ``"config set"``).

    Returns
    -------
    str
        Parent name (e.g., ``"config"``) or an empty string when none exists.
    """
    parts = qualified_name.split()
    if len(parts) <= 1:
        return ""
    return " ".join(parts[:-1])


def _command_summary(command: CommandData) -> str | None:
    """Return a single-line summary for a command, if available.

    For **message** commands, this prefers the first line of the function's
    docstring and falls back to ``command.description``. For **interaction**
    commands, the order is reversed (prefer ``command.description`` first).

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.

    Returns
    -------
    str | None
        Summary line or ``None`` when no summary is available.
    """
    if command.type == "message":
        if command.docstring:
            stripped = command.docstring.strip()
            if stripped:
                first_line = stripped.splitlines()[0].strip()
                if first_line:
                    return first_line
        if command.description:
            return command.description.strip()
        return None
    if command.description:
        return command.description.strip()
    if command.docstring:
        stripped = command.docstring.strip()
        if stripped:
            first_line = stripped.splitlines()[0].strip()
            if first_line:
                return first_line
    return None


_DOC_SECTION_BREAKS = {
    "parameters",
    "returns",
    "yields",
    "raises",
    "examples",
    "notes",
    "see also",
    "references",
    "warnings",
    "usage",
}


def _command_long_description(command: CommandData) -> str | None:
    """Return narrative docstring details for **interaction** commands.

    Message commands intentionally omit long descriptions to keep panels concise.
    For interaction commands, only free-form prose between the summary line and
    the first structured docstring section (``Parameters``, ``Returns``, etc.) is
    surfaced. This keeps help output focused while preserving parameter
    descriptions for dedicated argument panels.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.

    Returns
    -------
    str | None
        Remaining prose joined by newlines, or ``None`` when absent.
    """
    if not command.docstring or command.type == "message":
        return None

    lines = [line.rstrip() for line in command.docstring.strip().splitlines()]
    if len(lines) <= 1:
        return None

    remainder: list[str] = []
    for raw in lines[1:]:
        stripped = raw.strip()
        if not stripped:
            if remainder:
                remainder.append("")
            continue

        if stripped.lower() in _DOC_SECTION_BREAKS:
            break
        if all(ch == "-" for ch in stripped):
            break

        remainder.append(stripped)

    while remainder and not remainder[-1].strip():
        remainder.pop()

    if not remainder:
        return None

    return "\n".join(remainder)


def _build_usage_line(command: CommandData, prefix: str) -> str:
    """Render a usage string for a command.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.
    prefix : str
        Effective display prefix for message commands.

    Returns
    -------
    str
        Usage string such as ``",ping"`` or ``"/config set <key> <value>"``.
    """
    qualified = command.qualified_name.strip()
    base = f"/{qualified}" if command.type == "interaction" else f"{prefix}{qualified}"
    parts = [base]
    for parameter in command.parameters:
        opening, closing = ("<", ">") if parameter.required else ("[", "]")
        parts.append(f"{opening}{parameter.name}{closing}")
    return " ".join(parts)


def _collapse_separators(items: list[Any]) -> list[Any]:
    """Return ``items`` without leading, trailing, or consecutive separators."""
    collapsed: list[Any] = []
    for item in items:
        if isinstance(item, ui.Separator) and (
            not collapsed or isinstance(collapsed[-1], ui.Separator)
        ):
            continue
        collapsed.append(item)

    if collapsed and isinstance(collapsed[-1], ui.Separator):
        collapsed.pop()

    return collapsed


def _build_command_container(
    entry: HelpEntry, prefix: str, children: list[CommandData]
) -> ui.Container:
    """Build a command detail container (summary, usage, args, examples, children).

    Parameters
    ----------
    entry : HelpEntry
        Categorized command metadata for the panel being built.
    prefix : str
        Effective display prefix for message commands.
    children : list[CommandData]
        Child subcommands (for interaction command groups); empty when N/A.

    Returns
    -------
    disnake.ui.Container
        A fully composed container ready for rendering in the Help view.
    """
    command = entry.command
    command_title = f"{entry.category} command help"
    type_label = "Prefix command" if command.type == "message" else "Interaction command"
    meta_parts = [type_label]
    if command.has_subcommands:
        meta_parts.append("Command group")
    # Guard against empty/falsy metadata entries to avoid stray separators.
    meta = " • ".join(part for part in meta_parts if part)

    items: list[Any] = [
        ui.TextDisplay(f"**{command_title}**"),
    ]

    def _append_separator() -> None:
        """Append a separator if the previous item wasn't already one."""
        if items and not isinstance(items[-1], ui.Separator):
            items.append(ui.Separator())

    if meta:
        items.append(ui.TextDisplay(meta))

    items.append(ui.TextDisplay(f"Qualified name: `{command.qualified_name}`"))

    summary = _command_summary(command)
    if summary:
        items.append(ui.TextDisplay(summary))

    details = _command_long_description(command)
    if details:
        items.append(ui.TextDisplay(details))

    alias_labels: list[str] = []
    if command.aliases:
        if command.type == "interaction":
            alias_labels = [f"`/{alias}`" for alias in command.aliases]
        else:
            alias_labels = [f"`{prefix}{alias}`" for alias in command.aliases]

    if alias_labels:
        _append_separator()
        items.append(ui.TextDisplay("**Aliases**"))
        items.extend(ui.TextDisplay(f"• {label}") for label in alias_labels)

    requirement_sections = _command_requirement_sections(command)
    if requirement_sections:
        _append_separator()
        for title, lines in requirement_sections:
            items.append(ui.TextDisplay(f"**{title}**"))
            items.extend(ui.TextDisplay(f"• {line}") for line in lines)

    extra_information = _command_extra_information(command)
    if extra_information:
        _append_separator()
        items.append(ui.TextDisplay("**Extra information**"))
        items.extend(ui.TextDisplay(f"• {line}") for line in extra_information)

    if command.has_subcommands and children:
        _append_separator()
        items.append(ui.TextDisplay("**Subcommands**"))
        for child in children:
            child_label = _command_label(child, prefix)
            child_summary = _command_summary(child)
            if child_summary:
                items.append(ui.TextDisplay(f"• **{child_label}** — {child_summary}"))
            else:
                items.append(ui.TextDisplay(f"• **{child_label}**"))

    if not command.has_subcommands:
        usage_line = _build_usage_line(command, prefix)
        if usage_line:
            _append_separator()
            items.append(ui.TextDisplay("**Usage**"))
            items.append(ui.TextDisplay(f"```\n{usage_line}\n```"))

        parameter_lines = _parameter_lines(command.parameters)
        if parameter_lines:
            _append_separator()
            items.append(ui.TextDisplay("**Arguments**"))
            items.extend(ui.TextDisplay(line) for line in parameter_lines)

        example = _resolve_example(command, prefix)
        if example:
            _append_separator()
            items.append(ui.TextDisplay("**Example**"))
            items.append(ui.TextDisplay(f"`{example}`"))

    normalized_items = _collapse_separators(items)

    return ui.Container(
        *normalized_items,
        accent_colour=disnake.Colour(colors.embed),
    )


def _generate_auto_examples(command: CommandData, prefix: str) -> list[str]:
    """Generate simple, deterministic examples for a command.

    Strategy
    --------
    - If the command has required parameters, produce an example using **only**
      that minimal set; otherwise, produce the bare command.
    - Also produce a second example including both required and optional params.
    - For slash commands, demonstrate ``name:value`` tokens.
    - For message commands, demonstrate whitespace-separated tokens.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.
    prefix : str
        Effective display prefix for message commands.

    Returns
    -------
    list[str]
        One or two examples, ordered from simplest to more complete.
    """
    if command.type == "interaction":
        base = f"/{command.qualified_name}"
    else:
        base = f"{prefix}{command.qualified_name}"
    required_params = [parameter for parameter in command.parameters if parameter.required is True]
    optional_params = [
        parameter
        for parameter in command.parameters
        if parameter.required is False or parameter.required is None
    ]

    def render(params: list[CommandParameterData]) -> str:
        tokens: list[str] = []
        for parameter in params:
            sample_value = _sample_value(parameter.name)
            if command.type == "interaction":
                tokens.append(f"{parameter.name}:{sample_value}")
            else:
                tokens.append(sample_value)
        if tokens:
            return f"{base} {' '.join(tokens)}"
        return base

    examples: list[str] = []

    if required_params:
        examples.append(render(required_params))
    else:
        examples.append(base)

    if optional_params:
        examples.append(render(required_params + optional_params))

    return examples


def _sample_value(parameter_name: str) -> str:
    """Return a predictable example value derived from a parameter name.

    Parameters
    ----------
    parameter_name : str
        Name of a command parameter (e.g., ``"user_id"``).

    Returns
    -------
    str
        Example token such as ``"example-user-id"``.
    """
    cleaned = parameter_name.replace("_", "-") or "value"
    return f"example-{cleaned}"


def _resolve_example(command: CommandData, prefix: str) -> str | None:
    """Select an example string for a command.

    Preference order:
    1) Explicit :data:`extras['example']` if present and non-empty.
    2) The first generated example from :func:`_generate_auto_examples`.

    Parameters
    ----------
    command : CommandData
        Serializable command metadata.
    prefix : str
        Effective display prefix for message commands.

    Returns
    -------
    str | None
        An example string to display with the command, or ``None``.
    """
    if not command.parameters:
        return None

    usage = _build_usage_line(command, prefix)

    extras = command.extras or {}
    example = extras.get("example")
    if isinstance(example, str) and example.strip():
        cleaned = example.strip()
        if cleaned == usage:
            return None
        return cleaned

    auto_examples = _generate_auto_examples(command, prefix)
    if not auto_examples:
        return None

    for candidate in auto_examples:
        if candidate != usage:
            return candidate

    return auto_examples[0]


def _command_requirement_sections(command: CommandData) -> list[tuple[str, tuple[str, ...]]]:
    """Return titled requirement sections for ``command``."""
    extras = command.extras or {}

    primary = _normalize_requirement_field(extras.get("requirements"))
    additional = _normalize_requirement_field(extras.get("extra_requirements"))

    sections: list[tuple[str, tuple[str, ...]]] = []
    if primary:
        sections.append(("Requirements", primary))
    if additional:
        sections.append(("Extra requirements", additional))
    return sections


def _command_extra_information(command: CommandData) -> tuple[str, ...]:
    """Return auxiliary informational lines sourced from command extras."""
    extras = command.extras or {}
    raw = extras.get("extra_information")

    if raw is None:
        return ()
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if isinstance(raw, Iterable) and not isinstance(raw, (bytes, str)):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return tuple(cleaned)
    return ()


def _normalize_requirement_field(value: object) -> tuple[str, ...]:
    """Normalize a requirements extras field into a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Iterable) and not isinstance(value, (bytes, str)):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return tuple(cleaned)
    return ()


def _parameter_lines(parameters: list[CommandParameterData]) -> list[str]:
    """Render parameter descriptors as bullet lines for the help UI.

    Parameters
    ----------
    parameters : list[CommandParameterData]
        Ordered list of parameters captured from the command signature or
        slash options.

    Returns
    -------
    list[str]
        A list of markdown-ready bullet lines describing each parameter.
    """
    lines: list[str] = []
    for parameter in parameters:
        opening, closing = ("<", ">") if parameter.required else ("[", "]")
        description = parameter.description.strip() if parameter.description else ""
        description = " ".join(description.split())

        bullet = f"• **{opening}{parameter.name}{closing}**"
        lines.append(f"{bullet} — {description}" if description else bullet)
    return lines


def _truncate_description(description: str | None) -> str | None:
    """Trim a description to :data:`_MAX_DESCRIPTION_LENGTH` characters.

    Parameters
    ----------
    description : str | None
        Description text to trim.

    Returns
    -------
    str | None
        Trimmed description (with an ellipsis when truncated) or ``None`` if
        ``description`` is falsy.
    """
    if not description:
        return None

    trimmed = description.strip()
    return truncate(trimmed, _MAX_DESCRIPTION_LENGTH)
