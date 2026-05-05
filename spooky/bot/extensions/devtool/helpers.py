"""Helper utilities for devtool buyer/config workflows."""

from __future__ import annotations

from collections.abc import Sequence

import disnake
from spooky.ext.constants import (
    FATALITY_ROLE_ID,
    LEGIT_ROLE_ID,
    SEMI_LEGIT_MAIN_ROLE_ID,
    SEMI_LEGIT_VISUAL_ROLE_ID,
    SEMI_RAGE_MAIN_ROLE_ID,
    SEMI_RAGE_VISUAL_ROLE_ID,
    STATS_BOOSTER_ROLE_ID,
)
from spooky.models.entities.buyers import BuyerCode


def group_codes_by_product_and_role(
    rows: Sequence[BuyerCode],
) -> dict[str, dict[int, list[BuyerCode]]]:
    """Group code rows by product then role id for summary rendering."""
    grouped: dict[str, dict[int, list[BuyerCode]]] = {}
    for row in rows:
        product_bucket = grouped.setdefault(row.product.lower(), {})
        product_bucket.setdefault(int(row.role_id), []).append(row)
    return grouped


def build_member_code_summary(
    *,
    member: disnake.Member,
    codes_by_product_role: dict[str, dict[int, list[BuyerCode]]],
    note: str | None = None,
) -> str:
    """Render the role-based config summary for a member across products."""
    member_role_ids = {int(role.id) for role in member.roles}

    def _slot(product: str, role_id: int) -> str:
        if role_id not in member_role_ids:
            return "Open ticket to purchase the config."
        rows = codes_by_product_role.get(product, {}).get(role_id, [])
        if not rows:
            return "⚠️ Not configured yet."
        ordered = sorted(rows, key=lambda item: (item.color or "").lower())
        lines: list[str] = []
        for row in ordered:
            color_prefix = f"**{row.color}** • " if row.color else ""
            code_value = f"||{row.code}||" if product == "memesense" else row.code
            lines.append(f"- {color_prefix}Version `{row.version}`\n  Code: {code_value}")
        return "\n".join(lines)

    def _fatality_section() -> str:
        if FATALITY_ROLE_ID not in member_role_ids:
            return "Open ticket to purchase the config."
        fatality_rows_by_role = codes_by_product_role.get("fatality", {})
        all_rows = [
            row
            for rows in fatality_rows_by_role.values()
            for row in rows
            if int(row.role_id) != LEGIT_ROLE_ID or LEGIT_ROLE_ID in member_role_ids
        ]
        if not all_rows:
            return "⚠️ Not configured yet."
        ordered = sorted(
            all_rows,
            key=lambda item: (
                item.bundle.lower(),
                item.branch.lower(),
                (item.color or "").lower(),
            ),
        )
        lines: list[str] = []
        for row in ordered:
            title = f"**{row.bundle} • {row.branch}**"
            color_suffix = f" • {row.color}" if row.color else ""
            lines.append(f"- {title}{color_suffix}\n  Version `{row.version}`\n  Code: {row.code}")
        return "\n".join(lines)

    note_prefix = f"## NOTE\n{note.strip()}\n\n" if note is not None and note.strip() else ""
    return (
        f"{note_prefix}"
        "## CONFIG ACCESS SUMMARY\n"
        f"{member.mention}\n\n"
        "Your currently available config codes are listed below "
        "based on your assigned roles.\n\n"
        "# Memesense\n"
        "### Legit\n"
        f"{_slot('memesense', LEGIT_ROLE_ID)}\n\n"
        "### Semi-Legit • Main Branch\n"
        f"{_slot('memesense', SEMI_LEGIT_MAIN_ROLE_ID)}\n\n"
        "### Semi-Legit • Visuals Add-On\n"
        f"{_slot('memesense', SEMI_LEGIT_VISUAL_ROLE_ID)}\n\n"
        "### Semi-Rage • Main Branch\n"
        f"{_slot('memesense', SEMI_RAGE_MAIN_ROLE_ID)}\n\n"
        "### Semi-Rage • Visuals Add-On\n"
        f"{_slot('memesense', SEMI_RAGE_VISUAL_ROLE_ID)}\n\n"
        "### Stats-Booster\n"
        f"{_slot('memesense', STATS_BOOSTER_ROLE_ID)}\n\n"
        "# Fatality\n"
        f"{_fatality_section()}"
    )
