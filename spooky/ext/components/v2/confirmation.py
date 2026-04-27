"""Reusable yes/no confirmation view built atop :class:`BaseView`.

This lightweight helper provides a pair of **Yes/No** buttons that gate all
interactions to a specific user (via :class:`~spooky.ext.components.v2.base_view.BaseView`).
Consumers create the view, send it alongside an embed or message prompting the
user, and then await :meth:`~disnake.ui.View.wait` to inspect the
``confirmed`` attribute:

>>> view = ConfirmationView(user_id=ctx.author.id)
>>> message = await ctx.send(embed=prompt, view=view)
>>> view.bind_to_message(message)
>>> await view.wait()
>>> if view.confirmed:
...     ...  # proceed with the dangerous action

Notes
-----
- The view intentionally avoids overriding :meth:`on_timeout`; the
  :class:`BaseView` implementation handles disabling and cleaning up components
  when a timeout occurs.
- ``confirmed`` is ``True`` when the user presses **Yes**, ``False`` when **No**
  is chosen, and ``None`` when the view times out without interaction.
"""

from __future__ import annotations

from typing import Any

from disnake import ButtonStyle, MessageInteraction, ui

from .base_view import BaseView

__all__ = ["ConfirmationView"]


class ConfirmationView(BaseView):
    """Display Yes/No buttons and capture the user's response."""

    confirmed: bool | None

    def __init__(
        self,
        *,
        user_id: int,
        yes_label: str = "Yes",
        no_label: str = "No",
    ) -> None:
        """Initialise the confirmation view.

        Parameters
        ----------
        user_id:
            Discord user ID allowed to interact with the buttons.
        yes_label, no_label:
            Optional overrides for the affirmative/negative button labels.
        """
        super().__init__(user_id=user_id, timeout=60)
        self.confirmed = None
        self._yes_label = yes_label
        self._no_label = no_label
        self.yes_button.label = self._yes_label
        self.no_button.label = self._no_label

    @ui.button(label="Yes", style=ButtonStyle.success)
    async def yes_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Handle the affirmative response."""
        await self._finalise(inter, confirmed=True)

    @ui.button(label="No", style=ButtonStyle.danger)
    async def no_button(self, _: ui.Button[Any], inter: MessageInteraction[Any]) -> None:
        """Handle the negative response."""
        await self._finalise(inter, confirmed=False)

    async def _finalise(
        self,
        inter: MessageInteraction[Any],
        *,
        confirmed: bool,
    ) -> None:
        """Persist the result, disable components, and update the message."""
        self.confirmed = confirmed
        self.disable_components()
        # Allow callers to override labels without touching decorators.
        self.yes_button.label = self._yes_label
        self.no_button.label = self._no_label

        if not inter.response.is_done():
            await inter.response.edit_message(view=self)
        else:  # pragma: no cover - defensive; depends on interaction state
            await inter.edit_original_message(view=self)

        self.stop()

    def disable_components(self) -> None:  # type: ignore[override]
        """Disable components while preserving custom labels."""
        super().disable_components()
        self.yes_button.label = self._yes_label
        self.no_button.label = self._no_label
