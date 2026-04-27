"""Small helpers for modals and component gating.

This module centralizes tiny, reusable utilities for working with Disnake UI:

Utilities
---------
- :func:`generate_id` — Create a random 16-char hexadecimal ID (suitable for
  custom IDs in components/modals).
- :func:`wait_for_components` — Wait for one of a set of component interactions,
  **gated to a specific user**; gently rejects others ephemerally.
- :func:`send_and_wait_for_modal` — Show a modal and await its submission with
  timeout handling (returns ``None`` on timeout and logs a warning).

Examples
--------
Wait for one of several buttons, gated to the command invoker:

>>> inter = await wait_for_components(
...     client=bot,
...     components=(my_button_1, my_button_2),
...     user_id=ctx.author.id,
...     wait_timeout=30.0,
... )

Open a modal and wait up to 3 minutes for submission:

>>> modal_inter = await send_and_wait_for_modal(
...     inter,
...     title="Rename",
...     components=[
...         disnake.ui.TextInput(label="New name", custom_id="name", required=True),
...     ],
... )
>>> if modal_inter is None:
...     await inter.followup.send("You took too long.", ephemeral=True)

Notes
-----
- These helpers are intentionally small; they do not attempt complex state
  tracking. They pair well with your existing view/timeout patterns.
- Rejections for non-author interactions use :func:`spooky.ext.components.v2.card.status_card`.
"""

from __future__ import annotations

import asyncio
import os
from collections import abc
from typing import Any

import disnake
from disnake import ui
from loguru import logger
from spooky.ext.components.v2.card import status_card

__all__ = ["generate_id", "send_and_wait_for_modal", "wait_for_components"]


def generate_id() -> str:
    """Return a random hexadecimal ID (16 characters).

    Returns
    -------
    str
        A random hex string derived from 8 bytes of entropy (``os.urandom(8)``).

    Examples
    --------
    >>> cid = generate_id()
    >>> len(cid), all(c in "0123456789abcdef" for c in cid)
    (16, True)
    """
    return os.urandom(8).hex()


async def wait_for_components(
    client: disnake.Client,
    components: abc.Iterable[ui.MessageUIComponent],
    *,
    user_id: int,
    wait_timeout: float,
) -> disnake.MessageInteraction[Any]:
    """Wait for a message interaction on one of ``components`` from ``user_id``.

    Interactions from other users receive an ephemeral rejection using
    :func:`status_card`.

    Parameters
    ----------
    client : disnake.Client
        The bot/client instance used to ``wait_for`` interactions.
    components : Iterable[disnake.ui.MessageUIComponent]
        The components to listen for (must have ``custom_id`` values).
    user_id : int
        The only user allowed to trigger a successful match.
    wait_timeout : float
        Maximum time to wait (seconds). Uses ``asyncio.timeout`` internally.

    Returns
    -------
    disnake.MessageInteraction
        The interaction matching one of the specified component IDs **from the
        authorized user**.

    Raises
    ------
    TimeoutError
        If no authorized interaction is received within ``wait_timeout``.

    Notes
    -----
    - This helper loops until either (1) the authorized user interacts with a
      matching component or (2) the overall timeout elapses.
    - Non-author interactions are answered ephemerally with a friendly denial.
    """
    ids = {component.custom_id for component in components}

    def check(inter: disnake.MessageInteraction[Any]) -> bool:
        try:
            return inter.data.custom_id in ids  # type: ignore[attr-defined]
        except Exception:
            return False

    async with asyncio.timeout(wait_timeout):
        while True:
            inter: disnake.MessageInteraction[Any] = await client.wait_for(
                disnake.Event.message_interaction, check=check
            )

            if inter.author.id == user_id:
                return inter

            await inter.response.send_message(
                embed=status_card(
                    False,
                    description=f"Hey! Why are you trying to click <@{user_id}>'s button?",
                ),
                ephemeral=True,
            )


async def send_and_wait_for_modal(
    inter: disnake.Interaction[Any],
    *,
    title: str,
    components: ui.Components[ui.ModalUIComponent],
    wait_timeout: float = 60 * 3,
) -> disnake.ModalInteraction[Any] | None:
    """Send a modal and await its submission.

    Parameters
    ----------
    inter : disnake.Interaction
        The interaction to respond to with a modal.
    title : str
        Title for the modal.
    components : ui.Components[ui.ModalUIComponent]
        The modal components (inputs). See Disnake's modal component types.
    wait_timeout : float, default 180
        Maximum time (seconds) to wait for the modal submission.

    Returns
    -------
    disnake.ModalInteraction | None
        The modal submission interaction if received in time; otherwise ``None``.

    Notes
    -----
    - Logs a warning when a modal times out, including its generated ID.
    - Returned interaction may be used to access input values.
    """
    modal_id = generate_id()
    await inter.response.send_modal(custom_id=modal_id, title=title, components=components)

    def check(mi: disnake.ModalInteraction[Any]) -> bool:
        return mi.custom_id == modal_id

    try:
        return await inter.bot.wait_for(
            disnake.Event.modal_submit, check=check, timeout=wait_timeout
        )
    except TimeoutError:
        logger.warning(f"Modal {modal_id} timed out.")
        return None
