"""Custom view powering the interactive help containers.

This module provides :class:`HelpView`, an interactive, container-first UI for the
message-based Help system. Users can:

- Choose a **category** (including an **Overview** entry).
- Browse individual commands within a category.
- Navigate between commands with **Back/Next** buttons.
- Jump directly to a command index via a **Go to page** modal.
- Close the help panel while preserving the rendered container.

Design notes
------------
- The view renders **component v2** payloads by appending the currently active
  :class:`disnake.ui.Container` after the view children.
- Navigation controls are conditionally shown/hidden based on the current category
  and command index; single-item categories hide navigation.
- The view maintains internal keys (category/command) to avoid depending on labels.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Any

from disnake import (
    ButtonStyle,
    InteractionMessage,
    Message,
    MessageInteraction,
    ModalInteraction,
    SelectOption,
    ui,
)
from spooky.core import emojis
from spooky.ext.components.v2.base_view import BaseView
from spooky.ext.truncate import truncate

from .models import HelpCategory, HelpCommand, HelpMenu

__all__ = ["HelpView"]

_OPTION_LENGTH_LIMIT = 100
_GO_TO_LABEL = "Go to page"


class HelpView(BaseView):
    """Interactive view that swaps help containers based on user selection.

    Parameters
    ----------
    menu : HelpMenu
        Aggregated help content containing the **overview** container and all
        **categories** with their prebuilt command containers.
    user_id : int
        The user id allowed to interact with this view (owner-lock).
    initial_category : str | None
        Optional category key to activate when the view is first rendered.
    initial_command : str | None
        Optional command key to display within ``initial_category`` on load.
    focus_mode : bool
        When ``True``, render only the resolved topic (hide the category selector
        and limit browsing to the relevant commands).
    focus_command_keys : tuple[str, ...] | None
        Optional ordered command keys used to constrain the command pool when
        ``focus_mode`` is active.

    Attributes
    ----------
    _menu : HelpMenu
        The immutable data model used to build/select containers.
    _category_map : dict[str, HelpCategory]
        Quick look-up from category keys to their data (for selection handling).
    _container : disnake.ui.Container
        The currently active container (overview or a command's container).
    _current_category : str | None
        The currently selected category key (``None`` for Overview).
    _current_command : str | None
        The currently selected command key inside the active category, if any.
    _current_command_index : int | None
        The zero-based index of the active command within the category, if any.
    _navigation_visible : bool
        Whether the Back/Next/Goto/Close row is visible.
    category_select : disnake.ui.StringSelect
        Category selection control injected as a child item.
    back_button, skip_button, goto_button, close_button : disnake.ui.Button
        Navigation and dismissal buttons (defined via decorators).

    Notes
    -----
    - The view inherits timeout/interaction gating from :class:`BaseView`.
    - The UI renders as **[selects/buttons..., then active container]** to comply with
      container-first layouts.
    """

    _overview_value = "overview"

    def __init__(
        self,
        menu: HelpMenu,
        *,
        user_id: int,
        initial_category: str | None = None,
        initial_command: str | None = None,
        focus_mode: bool = False,
        focus_command_keys: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(user_id=user_id, timeout=120)
        self._menu = menu
        self._category_map: dict[str, HelpCategory] = {
            category.key: category for category in menu.categories
        }
        self._command_lookup: dict[str, HelpCommand] = {
            command.key: command for category in menu.categories for command in category.commands
        }
        self._browsable_map: dict[str, tuple[HelpCommand, ...]] = {
            category.key: tuple(command for command in category.commands if not command.hidden)
            for category in menu.categories
        }
        self._container: ui.Container = menu.overview
        self._current_category: str | None = None
        self._current_command: str | None = None
        self._current_command_index: int | None = None
        self._current_command_pool: tuple[HelpCommand, ...] | None = None
        self._navigation_visible = False
        self._focus_mode = focus_mode
        self._focus_command_keys = (
            tuple(dict.fromkeys(focus_command_keys)) if focus_command_keys else ()
        )

        self.category_select = ui.StringSelect(
            placeholder="Choose a category",
            min_values=1,
            max_values=1,
            options=[],
            custom_id="help:categories",
        )
        # Attach the callback explicitly since we don't use the decorator form here.
        self.category_select.callback = self._handle_category  # type: ignore[assignment]
        if not focus_mode:
            self.add_item(self.category_select)
        self._paging_items = [
            self.back_button,
            self.skip_button,
            self.goto_button,
        ]
        self._navigation_items = [
            self.close_button,
            *self._paging_items,
        ]

        self._set_overview()

        if initial_category:
            category = self._category_map.get(initial_category)
            if category is not None:
                self._set_category(category)
                if initial_command:
                    self._focus_on_command(category, initial_command)
                elif self._focus_command_keys:
                    self._focus_on_command(category, self._focus_command_keys[0])

    def build_component_input(self) -> list[Any]:
        """Return the component tree in render order for a message edit.

        The list contains:
        1) Category select.
        2) Navigation items (conditionally, based on visibility).
        3) The **active container** (overview or command details).

        Returns
        -------
        list[Any]
            The component v2-compatible payload for ``edit_message`` APIs.
        """
        components: list[Any] = []

        # Only include the category selector when the view actually exposes it
        # (focus mode omits it entirely).
        if self.category_select in self.children:
            components.append(self.category_select)

        components.append(self._container)

        navigation: list[Any] = [self.close_button]

        if self._navigation_visible:
            navigation.extend(self._paging_items)

        components.extend(navigation)
        return components

    async def _handle_category(self, inter: MessageInteraction[Any]) -> None:
        """Handle category selection changes.

        Parameters
        ----------
        inter : disnake.MessageInteraction[Any]
            The interaction raised by a category selection.

        Behavior
        --------
        - Selecting **Overview** restores the overview container.
        - Selecting a category switches to the first command in that category
          (or the overview again if the category is empty).
        """
        selected = self.category_select.values[0]
        if selected == self._overview_value:
            self._set_overview()
        else:
            category = self._category_map.get(selected)
            if category is None:
                await inter.response.defer()
                return
            self._set_category(category)

        await self._refresh_components(inter)

    def _set_overview(self) -> None:
        """Switch to the overview container and reset command selection.

        Side Effects
        ------------
        - Clears ``_current_category``, ``_current_command``, and index state.
        - Updates select defaults to **Overview**.
        - Hides navigation controls.
        """
        self._current_category = None
        self._current_command = None
        self._current_command_index = None
        self._current_command_pool = None
        self._container = self._menu.overview
        self._sync_category_options(self._overview_value)
        self._update_navigation_state()

    def _set_category(self, category: HelpCategory) -> None:
        """Switch to ``category`` and prime the first command.

        Parameters
        ----------
        category : HelpCategory
            The target category to activate.

        Notes
        -----
        If the category has no commands, the view falls back to the overview container.
        """
        self._current_category = category.key
        self._current_command = None
        self._current_command_index = None
        self._current_command_pool = None
        self._sync_category_options(category.key)
        browsable = self._browsable_map.get(category.key, ())
        if self._focus_mode:
            pool = self._build_focus_pool(category)
            if not pool:
                pool = browsable
        else:
            pool = browsable
        if not pool:
            self._container = self._menu.overview
            self._update_navigation_state()
            return
        self._select_command(category, 0, pool=pool)

    def _select_command(
        self,
        category: HelpCategory,
        index: int,
        *,
        pool: Sequence[HelpCommand] | None = None,
    ) -> None:
        """Select and render a command at ``index`` within ``category``.

        Parameters
        ----------
        category : HelpCategory
            Active category whose commands are being browsed.
        index : int
            Zero-based command index. Values outside valid range are clamped.
        pool : Sequence[HelpCommand] | None
            Optional command sequence to constrain navigation (e.g., skip hidden
            commands).

        Side Effects
        ------------
        - Updates ``_current_command`` and ``_current_command_index``.
        - Sets the active container to the selected command's container.
        - Shows/hides navigation as appropriate for the command count.
        """
        commands = tuple(pool) if pool is not None else tuple(category.commands)
        if not commands:
            self._current_command = None
            self._current_command_index = None
            self._current_command_pool = None
            self._container = self._menu.overview
            self._update_navigation_state()
            return

        clamped = max(0, min(index, len(commands) - 1))
        command = commands[clamped]
        self._current_command = command.key
        self._current_command_index = clamped
        self._current_command_pool = commands
        self._container = command.container
        self._update_navigation_state()

    def _get_current_category(self) -> HelpCategory | None:
        """Return the currently active :class:`HelpCategory`, if any."""
        if self._current_category is None:
            return None
        return self._category_map.get(self._current_category)

    def _build_focus_pool(self, category: HelpCategory) -> tuple[HelpCommand, ...]:
        """Return the command pool constrained by focus keys when applicable."""
        commands = tuple(category.commands)
        if not commands:
            return ()
        if not self._focus_command_keys:
            return commands

        ranking = {key: index for index, key in enumerate(self._focus_command_keys)}
        matched = [command for command in commands if command.key in ranking]
        if not matched:
            return commands
        matched.sort(key=lambda command: ranking[command.key])
        return tuple(matched)

    def _focus_on_command(self, category: HelpCategory, command_key: str) -> None:
        """Select ``command_key`` within ``category`` if present."""
        command = self._command_lookup.get(command_key)
        if command is None:
            return

        pool = self._current_command_pool or ()
        if pool and command in pool:
            index = pool.index(command)
            self._select_command(category, index, pool=pool)
            return

        focus_pool = self._build_focus_pool(category)
        if focus_pool and command in focus_pool:
            index = focus_pool.index(command)
            self._select_command(category, index, pool=focus_pool)
            return

        browsable = self._browsable_map.get(category.key, ())
        if browsable and command in browsable:
            index = tuple(browsable).index(command)
            self._select_command(category, index, pool=browsable)
            return

        self._select_command(category, 0, pool=(command,))

    def _update_navigation_state(self) -> None:
        """Enable/disable navigation items based on current selection.

        Rules
        -----
        - If no category/command is selected, navigation is hidden and disabled.
        - Back is disabled at index ``0``; Next is disabled at last index.
        - Goto is disabled for single-command categories.
        """
        pool = self._current_command_pool
        if (not pool) and self._current_category is not None:
            category = self._category_map.get(self._current_category)
            fallback = self._browsable_map.get(self._current_category, ())
            if category is not None and fallback:
                index = self._current_command_index or 0
                self._select_command(category, index, pool=fallback)
                return

        if pool is None or self._current_command_index is None or not pool:
            self._navigation_visible = False
            self.back_button.disabled = True
            self.skip_button.disabled = True
            self.goto_button.disabled = True
            self.goto_button.label = _GO_TO_LABEL
            return

        total = len(pool)
        index = max(0, min(self._current_command_index, total - 1))
        self._current_command_index = index
        self._navigation_visible = total > 1
        if total <= 1:
            self.back_button.disabled = True
            self.skip_button.disabled = True
            self.goto_button.disabled = True
            self.goto_button.label = _GO_TO_LABEL
            return

        self.back_button.disabled = index == 0
        self.skip_button.disabled = index == total - 1
        self.goto_button.disabled = False
        self.goto_button.label = f"Go to page ({index + 1}/{total})"

    def _sync_category_options(self, selected: str) -> None:
        """Update category selector entries and selection state.

        Parameters
        ----------
        selected : str
            The category key (or ``"overview"``) that should appear selected.
        """
        options = [
            SelectOption(
                label="Overview",
                value=self._overview_value,
                description="Instructions for navigating the help menu.",
                default=selected == self._overview_value,
            )
        ]

        for category in self._menu.categories:
            options.append(
                SelectOption(
                    label=_truncate_option_label(category.label),
                    value=category.key,
                    description=_truncate_option_description(category.description),
                    default=category.key == selected,
                )
            )

        self.category_select.options = options

    async def _refresh_components(self, inter: MessageInteraction[Any]) -> None:
        """Apply the current component tree to the interaction message.

        Parameters
        ----------
        inter : disnake.MessageInteraction[Any]
            The interaction to respond to.

        Notes
        -----
        - Uses ``response.edit_message`` if the response channel is open;
          otherwise falls back to ``edit_original_message``.
        - Exceptions are suppressed to keep the view responsive.
        """
        components = self.build_component_input()
        try:
            if inter.response.is_done():
                await inter.edit_original_message(components=components)
            else:
                await inter.response.edit_message(components=components)
        except Exception:
            pass

    async def handle_goto_submission(
        self,
        inter: ModalInteraction[Any],
        category_key: str,
        index: int,
        pool: Sequence[HelpCommand] | None = None,
    ) -> None:
        """Handle a submitted page number from the Go-to modal.

        Parameters
        ----------
        inter : disnake.ModalInteraction[Any]
            The modal submission interaction.
        category_key : str
            The key of the category to switch to.
        index : int
            Zero-based command index to activate within that category.
        """
        category = self._category_map.get(category_key)
        commands = tuple(pool) if pool is not None else self._current_command_pool or ()
        if category is None or not commands:
            if not inter.response.is_done():
                await inter.response.defer(with_message=False)
            return

        self._current_category = category_key
        self._sync_category_options(category_key)
        clamped = max(0, min(index, len(commands) - 1))
        self._select_command(category, clamped, pool=commands)
        components = self.build_component_input()

        if not inter.response.is_done():
            with contextlib.suppress(Exception):
                await inter.response.defer(with_message=False)

        await self.bind_to_interaction(inter)
        message = await self._apply_modal_update(inter, components)
        await self._rebind_after_modal(inter, message)

    async def _apply_modal_update(
        self,
        inter: ModalInteraction[Any],
        components: Sequence[Any],
    ) -> Message | InteractionMessage | None:
        """Best-effort update helper for modal submissions.

        Parameters
        ----------
        inter : disnake.ModalInteraction[Any]
            The interaction generated by the modal submission.
        components : Sequence[Any]
            Component payload to apply to the original help message.

        Returns
        -------
        disnake.Message | disnake.InteractionMessage | None
            The edited message when an update path succeeds, otherwise ``None``.
        """
        editors: list[Callable[..., Awaitable[Any]]] = []

        edit_original_response = getattr(inter, "edit_original_response", None)
        if edit_original_response is not None:
            editors.append(edit_original_response)

        edit_original_message = getattr(inter, "edit_original_message", None)
        if edit_original_message is not None:
            editors.append(edit_original_message)

        followup = getattr(inter, "followup", None)
        edit_followup = getattr(followup, "edit_message", None) if followup is not None else None
        if edit_followup is not None:
            editors.append(partial(edit_followup, "@original"))

        for editor in editors:
            with contextlib.suppress(Exception):
                message = await editor(components=components)
                if message is not None:
                    return message

        message: Message | InteractionMessage | None = getattr(inter, "message", None)
        if message is None:
            message = self._bound_message

        if message is not None:
            with contextlib.suppress(Exception):
                return await message.edit(components=components)

        edit_cb = self._edit_cb
        if edit_cb is not None:
            with contextlib.suppress(Exception):
                return await edit_cb(components=components)

        return None

    async def _rebind_after_modal(
        self,
        inter: ModalInteraction[Any],
        message: Message | InteractionMessage | None,
    ) -> None:
        """Re-bind the view and restock it in the state store after a modal edit."""
        target_message: Message | InteractionMessage | None = message
        if target_message is None:
            target_message = getattr(inter, "message", None)
        if target_message is None:
            target_message = self._bound_message

        state = getattr(target_message, "_state", None)
        if state is None:
            state = getattr(inter, "_state", None)

        if isinstance(target_message, Message):
            edit_cb = getattr(inter, "edit_original_response", None)
            if edit_cb is None:
                edit_cb = getattr(inter, "edit_original_message", None)
            self.bind_to_message(target_message, edit_cb=edit_cb)

        if state is not None and not self.is_finished():
            message_id = getattr(target_message, "id", None)
            state.store_view(self, message_id)

    @ui.button(style=ButtonStyle.gray, emoji=emojis.page_return, row=1, disabled=True)
    async def back_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Navigate to the previous command within the current category.

        Parameters
        ----------
        _ : disnake.ui.Button[Any]
            The button instance (unused).
        inter : disnake.MessageInteraction[Any]
            The interaction raised by the click.
        """
        category = self._get_current_category()
        pool = self._current_command_pool
        if category is None or pool is None or self._current_command_index is None:
            await inter.response.defer()
            return
        if self._current_command_index == 0:
            await inter.response.defer()
            return
        self._select_command(category, self._current_command_index - 1, pool=pool)
        await self._refresh_components(inter)

    @ui.button(style=ButtonStyle.gray, emoji=emojis.page_forward, row=1, disabled=True)
    async def skip_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Navigate to the next command within the current category.

        Parameters
        ----------
        _ : disnake.ui.Button[Any]
            The button instance (unused).
        inter : disnake.MessageInteraction[Any]
            The interaction raised by the click.
        """
        category = self._get_current_category()
        pool = self._current_command_pool
        if category is None or pool is None or self._current_command_index is None:
            await inter.response.defer()
            return
        if self._current_command_index >= len(pool) - 1:
            await inter.response.defer()
            return
        self._select_command(category, self._current_command_index + 1, pool=pool)
        await self._refresh_components(inter)

    @ui.button(style=ButtonStyle.blurple, label=_GO_TO_LABEL, row=1, disabled=True)
    async def goto_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Open a modal to jump to a specific command index.

        Parameters
        ----------
        _ : disnake.ui.Button[Any]
            The button instance (unused).
        inter : disnake.MessageInteraction[Any]
            The interaction raised by the click.
        """
        category = self._get_current_category()
        pool = self._current_command_pool
        if category is None or pool is None or self._current_command_index is None:
            await inter.response.defer()
            return
        modal = HelpGoToPageModal(self, category, pool, self._current_command_index)
        await inter.response.send_modal(modal)

    @ui.button(style=ButtonStyle.red, label="Close", row=1)
    async def close_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Remove the help message and stop the view when the close button is pressed.

        Parameters
        ----------
        _ : disnake.ui.Button[Any]
            The button instance (unused).
        inter : disnake.MessageInteraction[Any]
            The interaction raised by the click.
        """
        message: Message | None = getattr(inter, "message", None)
        if message is None:
            message = self._bound_message
        try:
            if not inter.response.is_done():
                await inter.response.defer()
        except Exception:
            pass

        if message is not None:
            with contextlib.suppress(Exception):
                await message.delete()

        self.stop()


def _truncate_option_label(label: str) -> str:
    """Return ``label`` trimmed to the option length limit.

    Parameters
    ----------
    label : str
        The option label to potentially truncate.

    Returns
    -------
    str
        The original or truncated label.
    """
    return truncate(label, _OPTION_LENGTH_LIMIT)


def _truncate_option_description(description: str | None) -> str | None:
    """Return a truncated description bounded by the option length limit.

    Parameters
    ----------
    description : str | None
        The description text to truncate.

    Returns
    -------
    str | None
        The original or truncated description, or ``None`` when input is falsy.
    """
    if not description:
        return None

    return truncate(description, _OPTION_LENGTH_LIMIT)


class HelpGoToPageModal(ui.Modal):
    """Modal prompting the user for a command index within the current category.

    Parameters
    ----------
    view : HelpView
        The owning view used to resolve and apply the selection.
    category : HelpCategory
        The category whose commands are being paged.
    pool : Sequence[HelpCommand]
        Ordered command pool used for pagination.
    current_index : int
        The zero-based index currently selected when opening the modal.

    Attributes
    ----------
    page_input : disnake.ui.TextInput
        The numeric input control used to capture the desired page number.
    _view : HelpView
        Back-reference to the owning view.
    _category_key : str
        Cached category key for the submission callback.
    _pool : tuple[HelpCommand, ...]
        Cached command pool used for pagination.
    _total : int
        Total number of commands available for navigation.
    """

    def __init__(
        self,
        view: HelpView,
        category: HelpCategory,
        pool: Sequence[HelpCommand],
        current_index: int,
    ) -> None:
        self._view = view
        self._category_key = category.key
        self._pool = tuple(pool)
        self._total = len(self._pool) or 1
        placeholder = f"1-{self._total}" if self._total else "1"
        text_input = ui.TextInput(
            label="Command number",
            min_length=1,
            max_length=4,
            value=str(current_index + 1),
            placeholder=placeholder,
            custom_id="help:goto:page",
        )
        super().__init__(title=f"{category.label} commands", components=[text_input])
        self.page_input = text_input

    async def callback(self, inter: ModalInteraction[Any]) -> None:  # type: ignore[override]
        """Validate and apply the target page index input by the user.

        Parameters
        ----------
        inter : disnake.ModalInteraction[Any]
            The modal submission interaction.

        Behavior
        --------
        - Parses and validates the numeric input against ``[1, _total]``.
        - On success, calls :meth:`HelpView.handle_goto_submission`.
        - On failure, responds ephemerally with a short guidance message.
        """
        custom_id = getattr(self.page_input, "custom_id", None)
        raw_value = ""
        if custom_id is not None:
            raw_value = (inter.text_values.get(custom_id) or "").strip()
        if not raw_value:
            raw_value = (self.page_input.value or "").strip()
        try:
            target = int(raw_value)
        except ValueError:
            await inter.response.send_message(
                f"Enter a number between 1 and {self._total}.",
                ephemeral=True,
            )
            return

        if not 1 <= target <= self._total:
            await inter.response.send_message(
                f"Enter a number between 1 and {self._total}.",
                ephemeral=True,
            )
            return

        await self._view.handle_goto_submission(
            inter,
            self._category_key,
            target - 1,
            pool=self._pool,
        )
