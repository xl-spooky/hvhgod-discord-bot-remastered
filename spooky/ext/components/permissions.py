"""Helpers for guild permission checks on interactions.

This module centralizes small, typed utilities for consistent **guild permission**
handling in command and component interactions:

- Safely resolve an invoking ``Member`` from an interaction (:func:`get_member`).
- Check Discord-level permissions with graceful ``None`` handling (:func:`has_perms`).
- Check Discord permissions **or** app-level DB overrides (:func:`has_perms_or_override`).
- Ephemeral, user-friendly denial flow with owner/self bypasses (:func:`ensure_perms`).
- A decorator factory for application permissions in slash/app commands
  (:func:`require_app_permissions`).

Design & Behavior
-----------------
- **Guild-only enforcement**: Functions detect DM contexts and respond (or return False)
  with a standardized ephemeral message.
- **Owner bypass**: Guild owners automatically pass checks.
- **Self bypass (optional)**: Useful for moderation actions targeting the invoker.
- **DB overrides**: Uses :class:`~spooky.models.UserPermissionOverride` to allow granular
  allow/deny separate from Discord role permissions.
- **Friendly failures**: :func:`ensure_perms` replies ephemerally on failure and marks
  the interaction to prevent duplicate error messages downstream.

Examples
--------
Require one of several permissions:

>>> ok = await has_perms_or_override(inter, "manage_guild", "manage_messages")

Require all permissions, with ephemeral error if not satisfied:

>>> await ensure_perms(
...     inter,
...     require_all=("manage_roles", "manage_permissions"),
...     error="You need Manage Roles and Manage Permissions."
... )

Decorator usage in a slash command:

>>> @require_app_permissions("manage_guild")
... async def cmd(inter):
...     ...

Notes
-----
- All permission names must match attributes on :class:`disnake.Permissions` or be
  members of :class:`~spooky.models.entities.permissions.AppPermission`.
- For complex policy needs (e.g., deny-wins over allow), extend or replace these helpers.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterable
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import disnake
from disnake.ext import commands
from spooky.bot import Spooky
from spooky.ext.components.v2.card import status_card
from spooky.models import UserPermissionOverride, ensure_member
from spooky.models.entities.permissions import AppPermission

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

__all__ = [
    "ensure_perms",
    "get_member",
    "has_perms",
    "has_perms_or_override",
    "require_app_permissions",
]


async def get_member(
    inter: disnake.MessageInteraction[Any] | disnake.ApplicationCommandInteraction[Any],
) -> disnake.Member | None:
    """Return the invoking :class:`disnake.Member` if available; otherwise ``None``.

    When the interaction author is not already a :class:`disnake.Member`, this
    helper falls back to :func:`spooky.models.ensure_member` for cached
    resolution.

    Parameters
    ----------
    inter :
        The interaction from which to resolve the invoking member.

    Returns
    -------
    disnake.Member | None
        The invoking guild member when available (guild context), otherwise ``None``.
    """
    author = inter.author
    if isinstance(author, disnake.Member):
        return author

    guild_id = inter.guild_id
    bot = inter.bot if isinstance(inter.bot, Spooky) else None
    if guild_id is None or bot is None:
        return None

    try:
        return await ensure_member(bot, int(guild_id), inter.author.id)
    except Exception:
        return None


def has_perms(member: disnake.Member | None, *perm_names: str) -> bool:
    """Return ``True`` if ``member`` has **every** permission in ``perm_names``.

    Parameters
    ----------
    member :
        The guild member to check. ``None`` yields ``False``.
    *perm_names :
        One or more attribute names from :class:`disnake.Permissions`
        (e.g., ``"manage_guild"``, ``"manage_roles"``).

    Returns
    -------
    bool
        ``True`` when all listed permissions are granted for ``member``.

    Notes
    -----
    - Missing members (DMs or partials) return ``False``.
    - Unknown permission names are treated as ``False``.
    """
    if member is None:
        return False
    perms = member.guild_permissions
    return all(bool(getattr(perms, name, False)) for name in perm_names)


PermissionName = str | AppPermission


async def ensure_perms(
    inter: disnake.MessageInteraction[Any] | disnake.ApplicationCommandInteraction[Any],
    *,
    require_all: Iterable[PermissionName] = (),
    require_any: Iterable[PermissionName] = (),
    allow_self_user_id: int | None = None,
    error: str | None = None,
) -> bool:
    """Ensure the invoker has required guild permissions; reply ephemeral on failure.

    This helper combines Discord role permissions **and** app-level DB overrides,
    supports guild owner and optional self bypasses, and sends a standardized
    ephemeral denial message when requirements are not met.

    Parameters
    ----------
    inter :
        The interaction to verify and optionally reply to.
    require_all :
        Iterable of permission names; **all** must be satisfied.
    require_any :
        Iterable of permission names; **at least one** must be satisfied.
    allow_self_user_id :
        If set and matches the invoker's ID, bypass checks (useful for
        self-targeting moderation actions).
    error :
        Optional custom denial message. Defaults to a generic message.

    Returns
    -------
    bool
        ``True`` if requirements are satisfied; otherwise ``False`` (after an
        ephemeral denial response is sent).

    Notes
    -----
    - In DM contexts (``guild_id is None``), an ephemeral guild-only message is sent.
    - Owner bypass applies if the invoker is the guild owner.
    - Marks the interaction with ``_spooky_error_sent = True`` to help callers avoid
      duplicate error messages.
    """
    if inter.guild_id is None:
        # Respond appropriately depending on interaction state
        try:
            if getattr(inter.response, "is_done", lambda: False)():
                await inter.followup.send(
                    embed=status_card(False, "This action is guild-only."), ephemeral=True
                )
            else:
                await inter.response.send_message(
                    embed=status_card(False, "This action is guild-only."), ephemeral=True
                )
        finally:
            # Mark that we already responded with an error to avoid double-sends
            with contextlib.suppress(Exception):
                setattr(inter, "_spooky_error_sent", True)
        return False

    if allow_self_user_id is not None and inter.author.id == allow_self_user_id:
        return True

    # Guild owner bypass (guard Optional owner_id)
    try:
        if inter.guild is not None:
            owner_id = inter.guild.owner_id  # may be int | None in stubs
            if owner_id is not None and owner_id == inter.author.id:
                return True
    except Exception:
        pass

    all_perms = tuple(require_all)
    any_perms = tuple(require_any)

    ok_all = True
    if all_perms:
        for perm in all_perms:
            if not await has_perms_or_override(inter, perm, allow_self_user_id=allow_self_user_id):
                ok_all = False
                break

    ok_any = True
    if any_perms:
        ok_any = await has_perms_or_override(
            inter, *any_perms, allow_self_user_id=allow_self_user_id
        )

    if ok_all and ok_any:
        return True

    # Send ephemeral denial using initial response if possible, else followup
    try:
        if getattr(inter.response, "is_done", lambda: False)():
            await inter.followup.send(
                embed=status_card(False, error or "You don't have permission to do this."),
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                embed=status_card(False, error or "You don't have permission to do this."),
                ephemeral=True,
            )
    finally:
        # Mark that we already responded with an error to avoid double-sends
        with contextlib.suppress(Exception):
            setattr(inter, "_spooky_error_sent", True)
    return False


async def has_perms_or_override(
    inter: disnake.MessageInteraction[Any] | disnake.ApplicationCommandInteraction[Any],
    *perm_names: PermissionName,
    allow_self_user_id: int | None = None,
) -> bool:
    """Return ``True`` if invoker satisfies **any** of the given permissions.

    Checks **either** Discord guild permissions (via role grants) **or** an
    app-level DB override in :class:`~spooky.models.UserPermissionOverride`.
    Does *not* send a response on failure.

    Parameters
    ----------
    inter :
        The interaction whose author will be tested.
    *perm_names :
        One or more permission names (strings or :class:`AppPermission` enum members).
    allow_self_user_id :
        Optional bypass when the invoker matches the specified user ID.

    Returns
    -------
    bool
        ``True`` if at least one permission is satisfied, otherwise ``False``.

    Notes
    -----
    - Returns ``False`` in DMs.
    - Owner bypass applies (guild owner always passes).
    - Invalid permission names are ignored (treated as False).
    """
    if inter.guild_id is None:
        return False
    if allow_self_user_id is not None and inter.author.id == allow_self_user_id:
        return True
    # Guild owner bypass (guard Optional owner_id)
    try:
        if inter.guild is not None:
            owner_id = inter.guild.owner_id
            if owner_id is not None and owner_id == inter.author.id:
                return True
    except Exception:
        pass
    member = await get_member(inter)
    for name in perm_names:
        pname = name.value if isinstance(name, AppPermission) else name
        if has_perms(member, pname):
            return True
        try:
            gid = inter.guild_id
            assert gid is not None
            if await UserPermissionOverride.filter(
                guild_id=gid,
                user_id=inter.author.id,
                perm_name=pname,
                allowed=True,
            ).exists():
                return True
        except Exception:
            continue
    return False


def require_app_permissions(
    *perms: PermissionName,
    any_: bool = False,
    allow_self: bool = False,
) -> Callable[[F], F]:
    """Return a :func:`disnake.ext.commands.check` enforcing app permissions.

    The returned decorator validates the invoker against Discord permissions
    **or** DB overrides. It supports "any-of" vs "all-of" semantics and an
    optional self-bypass (when the command targets the invoker).

    Parameters
    ----------
    *perms : PermissionName
        Permission names (string or :class:`AppPermission`). When ``any_`` is
        ``False`` (default), **all** must be satisfied; otherwise at least one.
    any_ : bool, default False
        If ``True``, require **any** permission among ``perms``. If ``False``,
        require **all**.
    allow_self : bool, default False
        If ``True``, bypass permission checks when the invoker is the target user.
        The command should set an attribute (e.g., ``inter.target_user_id``) for
        this to apply.

    Returns
    -------
    Callable[[F], F]
        A decorator suitable for Disnake command callbacks.

    Examples
    --------
    >>> @require_app_permissions(AppPermission.MANAGE_GUILD)
    ... async def cmd(inter): ...

    >>> @require_app_permissions("manage_guild", "manage_roles", any_=True)
    ... async def cmd(inter): ...
    """
    normalized_perms: tuple[str, ...] = tuple(
        perm.value if isinstance(perm, AppPermission) else str(perm) for perm in perms
    )

    async def predicate(invocation: disnake.AppCmdInter[Any] | commands.Context[Any]) -> bool:
        """Check permissions for either an interaction or context invocation."""

        async def _dispatch_context_error(ctx: commands.Context[Any], message: str) -> None:
            handler = getattr(ctx, "error", None)
            if callable(handler):
                result = handler(message)
                if isinstance(result, Awaitable):
                    await result
                return
            await ctx.send(message)

        # Try self-bypass via an attribute set by the command (optional)
        allow_self_user_id = None
        if allow_self:
            try:
                allow_self_user_id = getattr(invocation, "target_user_id", None)
            except Exception:
                allow_self_user_id = None

        if isinstance(invocation, commands.Context):
            ctx = invocation
            if ctx.guild is None:
                await _dispatch_context_error(ctx, "This action is guild-only.")
                return False

            proxy = SimpleNamespace(
                guild_id=ctx.guild.id,
                guild=ctx.guild,
                author=ctx.author,
                bot=getattr(ctx, "bot", None),
            )

            if any_:
                ok = await has_perms_or_override(
                    cast(Any, proxy),
                    *perms,
                    allow_self_user_id=allow_self_user_id,
                )
            else:
                ok = True
                for perm in perms:
                    if not await has_perms_or_override(
                        cast(Any, proxy),
                        perm,
                        allow_self_user_id=allow_self_user_id,
                    ):
                        ok = False
                        break

            if ok:
                return True

            await _dispatch_context_error(ctx, "You don't have permission to do this.")
            return False

        if any_:
            return await has_perms_or_override(
                invocation,
                *perms,
                allow_self_user_id=allow_self_user_id,
            )
        # require all
        return await ensure_perms(
            invocation,
            require_all=perms,
            allow_self_user_id=allow_self_user_id,
        )

    setattr(
        predicate,
        "__spooky_permission_meta__",
        {
            "kind": "app",
            "permissions": normalized_perms,
            "any": any_,
            "override": True,
        },
    )

    # Pylance expects Context-based checks; cast to satisfy types.
    return cast(Callable[[F], F], commands.check(cast(Any, predicate)))
