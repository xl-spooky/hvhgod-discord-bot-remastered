"""Generic pagination view for embed lists (v2).

This module provides a lightweight, button-driven paginator for cycling through
a pre-built list of :class:`disnake.Embed` objects. It is designed for compact,
predictable navigation with minimal state:

- Fast-first/previous/next/fast-last navigation controls
- An index button that displays the current page and closes the view when pressed
- Automatic enable/disable logic for boundary buttons
- Single-embed optimization that disables navigation entirely

Example
-------
>>> view = PaginationView(embeds, user_id=ctx.author.id)
>>> await ctx.send(embed=embeds[0], view=view)

Notes
-----
This paginator assumes the embed list is immutable while the view is active.
If you need dynamic content, rebuild the view with the updated embed list.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import disnake
from disnake import ButtonStyle, MessageInteraction, ui
from spooky.core import emojis
from spooky.ext.components.v2.base_view import BaseView

__all__ = ["PaginationView"]

AttachmentFactory = Callable[[], disnake.File]


class PaginationView(BaseView):
    """Paginate through a list of embeds with navigation buttons.

    The view manages an internal page index and exposes first/previous/next/last
    buttons, plus a red index button that both displays the current position and
    acts as a "close" control for the paginator.

    Parameters
    ----------
    embeds :
        Ordered list of :class:`disnake.Embed` objects to paginate through.
    user_id :
        The user ID permitted to interact with this view (enforced by ``BaseView``).

    Attributes
    ----------
    embeds :
        The original list of embeds provided to the constructor.
    index :
        The zero-based index of the currently selected page.

    Behavior
    --------
    - If only a single embed is provided, all navigation buttons are disabled.
    - Boundary buttons (first/prev or next/last) are disabled when on the first
      or last page respectively.
    """

    def __init__(
        self,
        embeds: list[disnake.Embed],
        *,
        user_id: int,
        attachments: Sequence[Sequence[AttachmentFactory]] | None = None,
    ) -> None:
        """Initialise the paginator and seed button state.

        The index label is set to ``"1/N"`` where N is the number of embeds.
        If ``N == 1``, navigation buttons are disabled.

        Parameters
        ----------
        embeds :
            The list of embeds to browse.
        user_id :
            The ID of the user allowed to operate the paginator.
        attachments :
            Optional sequence mapping each page to callables that open fresh
            :class:`disnake.File` objects when the page is displayed. When
            provided, attachments from previous pages are cleared automatically
            during navigation.
        """
        super().__init__(user_id=user_id, timeout=60)
        self.embeds = embeds
        self.index = 0
        self.attachments: list[list[AttachmentFactory]] = [list(page) for page in attachments or []]
        self.index_button.label = f"{self.index + 1}/{len(self.embeds)}"

        if len(embeds) == 1:
            self.disable_navigation_buttons()

    @ui.button(disabled=True, style=ButtonStyle.gray, emoji=emojis.page_fast_return, row=0)
    async def first_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Jump to the first page and update the message.

        Parameters
        ----------
        _ :
            The button instance (unused).
        inter :
            The interaction context for the button press.
        """
        self.index = 0
        self.update_buttons()
        await self._edit_page(inter)

    @ui.button(disabled=True, style=ButtonStyle.gray, emoji=emojis.page_return, row=0)
    async def previous_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Move one page backward and update the message.

        Parameters
        ----------
        _ :
            The button instance (unused).
        inter :
            The interaction context for the button press.
        """
        self.index -= 1
        self.update_buttons()
        await self._edit_page(inter)

    @ui.button(style=ButtonStyle.red, row=0)
    async def index_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Display the index label and close the paginator when pressed.

        This acts as a "confirm/close" control—pressing it deletes the original
        response and stops the view.

        Parameters
        ----------
        _ :
            The button instance (unused).
        inter :
            The interaction context for the button press.
        """
        await inter.response.defer()
        await inter.delete_original_response()
        self.stop()

    @ui.button(style=ButtonStyle.gray, emoji=emojis.page_forward, row=0)
    async def next_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Advance one page forward and update the message.

        Parameters
        ----------
        _ :
            The button instance (unused).
        inter :
            The interaction context for the button press.
        """
        self.index += 1
        self.update_buttons()
        await self._edit_page(inter)

    @ui.button(style=ButtonStyle.gray, emoji=emojis.page_fast_forward, row=0)
    async def last_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Jump to the final page and update the message.

        Parameters
        ----------
        _ :
            The button instance (unused).
        inter :
            The interaction context for the button press.
        """
        self.index = len(self.embeds) - 1
        self.update_buttons()
        await self._edit_page(inter)

    def update_buttons(self) -> None:
        """Sync button enabled/disabled state and index label with the current page.

        This method:
        - Disables first/previous when on the first page
        - Disables next/last when on the final page
        - Updates the index label to ``"{index+1}/{total}"``
        """
        self.first_button.disabled = self.index == 0
        self.previous_button.disabled = self.index == 0
        self.index_button.label = f"{self.index + 1}/{len(self.embeds)}"
        self.next_button.disabled = self.index == len(self.embeds) - 1
        self.last_button.disabled = self.index == len(self.embeds) - 1

    def disable_navigation_buttons(self) -> None:
        """Disable all navigation buttons (first/prev/next/last).

        Useful when only a single page exists or navigation should be locked.
        """
        self.first_button.disabled = True
        self.previous_button.disabled = True
        self.next_button.disabled = True
        self.last_button.disabled = True

    def get_current_embed(self) -> disnake.Embed:
        """Return the embed for the current page index.

        Returns
        -------
        disnake.Embed
            The embed corresponding to :attr:`index`.
        """
        return self.embeds[self.index]

    def get_current_files(self) -> list[disnake.File]:
        """Return freshly-opened attachments for the current page."""
        if not self.attachments:
            return []
        if self.index >= len(self.attachments):
            return []
        return [factory() for factory in self.attachments[self.index]]

    async def _edit_page(self, inter: MessageInteraction[Any]) -> None:
        """Edit the message for the current page, swapping attachments as needed."""
        files = self.get_current_files()
        kwargs: dict[str, Any] = {
            "embed": self.get_current_embed(),
            "view": self,
            "attachments": [],
        }
        if files:
            kwargs["files"] = files
        await inter.response.edit_message(**kwargs)
