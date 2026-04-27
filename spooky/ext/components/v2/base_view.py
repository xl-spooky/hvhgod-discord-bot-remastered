"""Shared base view for interactive UI components (v2).

`BaseView` provides a reusable foundation for Discord UI built with
``disnake.ui.View``. The v2 module centralises shared behaviour for all views,
and pairs with :mod:`spooky.ext.components.v2.card` for consistent feedback
messaging.

Features
--------
- Per-user interaction gating with friendly rejection feedback
- Convenience helpers to enable/disable all components or only buttons
- Message binding so timed-out views can update themselves
- Safe fallbacks for ephemeral/slash-command responses

Example
-------
>>> view = SomeChildView(user_id=ctx.author.id)
>>> msg = await ctx.send("Pick one:", view=view)
>>> view.bind_to_message(msg)

Notes
-----
- Always pass the intended ``user_id`` to restrict interactions.
- For ephemeral or slash-command flows, prefer :meth:`bind_to_interaction`
  so the view can still edit itself on timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import disnake
from disnake import MessageInteraction, ui
from spooky.ext.components.v2.card import status_card
from typing_extensions import override

__all__ = ["BaseView"]


class BaseView(ui.View):
    """Base class for interactive views with auth, binding, and helpers.

    Parameters
    ----------
    user_id:
        The only user allowed to interact with this view's components.
    timeout:
        Auto-timeout in seconds (defaults to ``60``). Once elapsed the view
        disables all components and attempts to update the bound message.

    Attributes
    ----------
    children :
        Runtime-populated component list (buttons, selects, etc.). Type is exposed
        for editor/tooling assistance.
    timeout : int
        Timeout in seconds after which the view will stop and be disabled.
    user_id : int
        The authorised user's ID. Other users receive an ephemeral rejection.
    message : ClassVar[str]
        Template used when rejecting unauthorised interactions.
    _bound_message : disnake.Message | None
        When set via :meth:`bind_to_message` or :meth:`bind_to_interaction`,
        the message this view will attempt to edit on timeout.
    _edit_cb : Callable[..., Awaitable[Any]] | None
        Fallback editor used for ephemeral/slash-command flows where the
        original message is not directly accessible.
    """

    # Disnake populates these at runtime; we surface a helpful type for tooling.
    children: list[ui.Button[None] | ui.BaseSelect[Any, Any, None]]  # type: ignore[assignment]
    timeout: int
    user_id: int

    message: ClassVar[str] = "Hey! Why are you trying to click <@{self.user_id}>'s button?"

    _bound_message: disnake.Message | None
    _edit_cb: Callable[..., Awaitable[Any]] | None

    def __init__(self, *, user_id: int, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self._bound_message = None
        self._edit_cb = None

    @override
    async def interaction_check(self, inter: MessageInteraction[Any], /) -> bool:
        """Gate interactions to the authorised user and politely reject others.

        Parameters
        ----------
        inter :
            The incoming interaction.

        Returns
        -------
        bool
            ``True`` when the author is authorised and handling should proceed;
            ``False`` after sending an ephemeral rejection embed to others.
        """
        if inter.author.id == self.user_id:
            return True

        await inter.response.send_message(
            embed=status_card(
                False,
                description=self.message.format(self=self, inter=inter),
            ),
            ephemeral=True,
        )
        return False

    def disable_all_buttons(self) -> None:
        """Disable only :class:`disnake.ui.Button` components.

        This leaves other interactive elements (e.g., selects) unchanged.
        Useful when you want to lock primary actions but keep menus active.
        """
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True

    def disable_components(self) -> None:
        """Disable every component (buttons, selects, etc.)."""
        for child in self.children:
            child.disabled = True

    def enable_components(self) -> None:
        """Enable every component (buttons, selects, etc.)."""
        for child in self.children:
            child.disabled = False

    def bind_to_message(
        self,
        message: disnake.Message,
        *,
        edit_cb: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        """Bind the view to a concrete message so it can edit itself on timeout.

        Parameters
        ----------
        message :
            The message to update when the view times out.
        edit_cb : Callable[..., Awaitable[Any]] | None, optional
            Optional fallback editor used when direct message edits fail (for
            example, ephemeral responses updated via ``edit_original_response``).
        """
        self._bound_message = message
        if edit_cb is not None:
            self._edit_cb = edit_cb

    async def bind_to_interaction(
        self,
        inter: MessageInteraction[Any]
        | disnake.ApplicationCommandInteraction[Any]
        | disnake.ModalInteraction[Any],
    ) -> None:
        """Bind to the original interaction message and store a fallback editor.

        Use this when the view was attached via ``edit_original_response`` or a slash
        command response (including ephemeral responses).

        Parameters
        ----------
        inter :
            The interaction whose original response should be used for edits.

        Notes
        -----
        - Stores a safe editor callable for ephemeral/slash-command flows.
        - Attempts to cache the underlying message if accessible.
        """
        edit_cb = getattr(inter, "edit_original_response", None)
        if edit_cb is None:
            edit_cb = getattr(inter, "edit_original_message", None)
        if edit_cb is not None:
            self._edit_cb = edit_cb

        message = getattr(inter, "message", None)
        if isinstance(message, disnake.Message):
            self._bound_message = message
            return

        try:
            self._bound_message = await inter.original_message()
        except Exception:
            self._bound_message = None

    @override
    async def on_timeout(self) -> None:
        """Disable all components, clear them from the message, and delete it.

        Behavior
        --------
        - Disables all components to prevent further interaction.
        - Removes the component tree from the bound message when accessible.
        - Waits three seconds before attempting to delete the message.
        - Falls back to any stored editor callback for ephemeral flows.
        - Silently ignores edit/delete errors and always stops the view.
        """
        self.disable_components()
        message = self._bound_message
        edit_cb = self._edit_cb

        try:
            if message is not None:
                with contextlib.suppress(Exception):
                    await message.edit(view=None)

                with contextlib.suppress(Exception):
                    await asyncio.sleep(3)
                    await message.delete()
            elif edit_cb is not None:
                with contextlib.suppress(Exception):
                    await edit_cb(view=None)
        finally:
            self.stop()
