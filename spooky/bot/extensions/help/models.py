"""Dataclasses used by the help extension.

These dataclasses define the **structured data model** for the message-based
help system. They decouple raw command metadata from the final rendered
containers, allowing the help UI to efficiently build pages and perform
navigation without recalculating layout.

Overview
--------
The help system is composed of four main entities:

- :class:`HelpEntry` — Lightweight pair of category + command metadata extracted
  from the bots command loader.
- :class:`HelpCommand` — Fully rendered, display-ready command entry with a
  prebuilt :class:`disnake.ui.Container`.
- :class:`HelpCategory` — Group of related commands under a shared label.
- :class:`HelpMenu` — Top-level container aggregating the overview and all
  categories, used by :class:`~spooky.bot.extensions.help.view.HelpView`.

Design notes
------------
- ``ui.Container`` objects are prebuilt once per command/category to avoid
  repetitive UI recomposition during pagination.
- Slots are enabled on all dataclasses to reduce per-instance memory usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from disnake import ui
from spooky.bot.command_loader import CommandData

__all__ = [
    "HelpCategory",
    "HelpCommand",
    "HelpEntry",
    "HelpMenu",
    "HelpTopicResolution",
]


@dataclass(slots=True)
class HelpEntry:
    """Categorized command metadata for help rendering.

    Attributes
    ----------
    category : str
        The display category under which this command is grouped.
    command : CommandData
        The raw metadata describing this command (name, description, parameters).
    """

    category: str
    command: CommandData


@dataclass(slots=True)
class HelpCommand:
    """Renderable help data for a single command.

    Attributes
    ----------
    key : str
        Internal unique identifier used for sorting or referencing.
    label : str
        Human-readable command label (e.g., ``/ban`` or `,help`).
    description : str | None
        Short description or summary for the command.
    container : disnake.ui.Container
        Prebuilt UI container representing this command in the help UI.
    topics : tuple[str, ...]
        Normalized search tokens that map to this command when resolving
        ``",help <topic>"`` queries.
    hidden : bool
        Whether the command should be excluded from default category browsing.
    """

    key: str
    label: str
    description: str | None
    container: ui.Container
    topics: tuple[str, ...] = field(default_factory=tuple)
    hidden: bool = False


@dataclass(slots=True)
class HelpCategory:
    """Collection of commands grouped under a category label.

    Attributes
    ----------
    key : str
        Internal unique key for the category.
    label : str
        Display label shown in the help menu.
    description : str | None
        Optional descriptive text summarizing the category.
    commands : list[HelpCommand]
        List of rendered commands that belong to this category.
    topics : tuple[str, ...]
        Normalized search tokens that map to this category when resolving
        ``",help <topic>"`` queries.
    """

    key: str
    label: str
    description: str | None
    commands: list[HelpCommand] = field(default_factory=list)
    topics: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class HelpMenu:
    """Aggregated help content with overview and per-category containers.

    Attributes
    ----------
    overview : disnake.ui.Container
        The root container shown on the home/overview page.
    categories : list[HelpCategory]
        List of all help categories and their associated commands.
    total_commands : int
        Total number of commands represented across all categories.
    topic_map : dict[str, tuple[str | None, str | None]]
        Lookup table mapping normalized topics to a tuple of
        ``(category_key, command_key)``. ``None`` entries point to the overview.
    topic_commands : dict[str, tuple[str, ...]]
        Mapping of normalized topics to the command keys that explicitly
        reference the topic. Used to focus help panels on the expected entries.
    """

    overview: ui.Container
    categories: list[HelpCategory] = field(default_factory=list)
    total_commands: int = 0
    topic_map: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    topic_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(slots=True)
class HelpTopicResolution:
    """Resolved topic lookup used for focused help views."""

    category_key: str | None
    command_key: str | None
    command_keys: tuple[str, ...] = field(default_factory=tuple)
