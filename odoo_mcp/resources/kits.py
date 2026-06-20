"""MCP resource: list every kit not in 'done' status with a part-status rollup.

Kits are ordered by lifecycle (``idea`` → ``planning`` → ``sourcing`` →
``building``) so the earliest-stage builds surface first. Each block carries
the kit name, status, a ``X wanted · Y ordered · Z received`` rollup, and a
short notes excerpt.

Detail (parts grouped by supplier) lives behind the ``odoo://kit/{id}``
resource template; this list view is intended for at-a-glance triage.
"""

from __future__ import annotations

from collections import Counter

import odoolib
from loguru import logger

from models import KitPartRecord, KitRecord

# Lifecycle states this resource surfaces, in display order. ``done`` is
# excluded — finished builds are reachable via odoo://kit/{id}.
_STATUS_ORDER: list[str] = ["idea", "planning", "sourcing", "building"]
_STATUS_INDEX: dict[str, int] = {s: i for i, s in enumerate(_STATUS_ORDER)}

# Notes excerpt cap for the list view; the full notes live on the detail tool.
_NOTES_EXCERPT_LIMIT = 140


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _notes_excerpt(notes: str) -> str:
    if len(notes) <= _NOTES_EXCERPT_LIMIT:
        return notes
    return notes[: _NOTES_EXCERPT_LIMIT - 1].rstrip() + "…"


def _render_kit(kit: KitRecord, counts: dict[str, int]) -> str:
    name = _scalar(kit.x_name, fallback="(unnamed)")
    status = _scalar(kit.x_studio_status)
    notes = _scalar(kit.x_studio_notes)

    rollup = (
        f"{counts.get('wanted', 0)} wanted · "
        f"{counts.get('ordered', 0)} ordered · "
        f"{counts.get('received', 0)} received"
    )

    lines: list[str] = [
        f"## {name} [{status}]",
        f"**Parts**: {rollup}",
    ]
    if notes:
        lines.append(f"**Notes**: {_notes_excerpt(notes)}")
    return "\n".join(lines)


def render(conn: odoolib.main.Connection) -> str:
    """Return a markdown string listing every kit not in ``done`` status.

    Kits are sorted by lifecycle order; part counts are aggregated by status
    per kit.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Markdown document, one section per kit.
    """
    kit_proxy = conn.get_model("x_kit")
    kit_rows: list[dict] = kit_proxy.search_read([], KitRecord.odoo_fields())
    all_kits = [KitRecord.from_odoo(r) for r in kit_rows]
    # Odoo selection values are user-defined; compare case-insensitively so the
    # filter and ordering work regardless of how the values were entered.
    kits = [k for k in all_kits if (k.x_studio_status or "").lower() != "done"]
    logger.info("kits resource: {} in-flight kit(s)", len(kits))

    if not kits:
        return "# Kits\n\nNo kits in flight.\n"

    kits.sort(
        key=lambda k: (
            _STATUS_INDEX.get((k.x_studio_status or "").lower(), 99),
            k.x_name or "",
        )
    )

    kit_ids = [k.id for k in kits if k.id is not None]
    part_proxy = conn.get_model("x_kit_part")
    part_rows: list[dict] = part_proxy.search_read(
        [("x_studio_kit_id", "in", kit_ids)],
        KitPartRecord.odoo_fields(),
    )
    parts = [KitPartRecord.from_odoo(r) for r in part_rows]
    logger.debug("kits resource: {} kit_part rows", len(parts))

    counts_by_kit: dict[int, Counter] = {k.id: Counter() for k in kits if k.id is not None}
    for part in parts:
        if part.x_studio_kit_id is None:
            continue
        kit_id = part.x_studio_kit_id[0]
        status = (part.x_studio_status or "").lower()
        if kit_id in counts_by_kit:
            counts_by_kit[kit_id][status] += 1

    sections: list[str] = ["# Kits", ""]
    for kit in kits:
        counts = dict(counts_by_kit.get(kit.id, Counter()))
        sections.append(_render_kit(kit, counts))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
