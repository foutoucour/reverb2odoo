"""MCP resource: full models catalog with gear/listing counts and wanna alerts."""

from __future__ import annotations

from collections import defaultdict

import odoolib
from loguru import logger

from models import ModelsRecord

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _build_spec_line(model: ModelsRecord) -> str:
    """Build the **Specs** line, omitting fields that are False/None/empty."""
    parts: list[str] = []
    scale = _scalar(model.x_studio_scale)
    neck = _label(model.x_studio_guitar_neck_feel_id)
    fretboard = _label(model.x_studio_fretboard_1)
    finish = _label(model.x_studio_finish)

    if scale:
        parts.append(f"scale={scale}")
    if neck:
        parts.append(f"neck={neck}")
    if fretboard:
        parts.append(f"fretboard={fretboard}")
    if finish:
        parts.append(f"finish={finish}")

    return " | ".join(parts)


def _render_model_section(
    model: ModelsRecord,
    gear_counts: dict[str, int],
    watching_count: int,
) -> str:
    """Render a single model block for the full catalog section."""
    name = _scalar(model.x_name, fallback="(unnamed)")
    brand = _label(model.x_studio_partner_id)
    model_type = _scalar(model.x_studio_model_type)
    wanna = "yes" if model.x_studio_wanna else "no"
    p25 = _scalar(model.x_price_p25)
    p50 = _scalar(model.x_price_p50)
    p75 = _scalar(model.x_price_p75)

    owned = gear_counts.get("owned", 0)
    for_sale = gear_counts.get("for_sale", 0)
    sold = gear_counts.get("sold", 0)

    lines: list[str] = [f"### {name}"]

    meta_parts: list[str] = []
    if brand:
        meta_parts.append(f"**Brand**: {brand}")
    if model_type:
        meta_parts.append(f"**Type**: {model_type}")
    meta_parts.append(f"**Wanna**: {wanna}")
    lines.append(" | ".join(meta_parts))

    spec_line = _build_spec_line(model)
    if spec_line:
        lines.append(f"**Specs**: {spec_line}")

    lines.append(f"**Brackets**: p25={p25} p50={p50} p75={p75}")
    lines.append(
        f"**Gear**: {owned} owned, {for_sale} for_sale, {sold} sold"
        f" | {watching_count} watching listings"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render(conn: odoolib.main.Connection) -> str:
    """Return a markdown catalog of all x_models with gear/listing counts.

    Queries ALL x_models records (no wanna filter), counts linked x_gear
    grouped by status and x_listing records with status=watching, then
    formats the result as markdown with two sections:

    1. Wanted models that have zero watching listings (alert section).
    2. Full catalog with specs, price brackets and counts.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Formatted markdown string.
    """
    models_proxy = conn.get_model("x_models")
    rows: list[dict] = models_proxy.search_read([], ModelsRecord.odoo_fields())
    all_models = [ModelsRecord.from_odoo(r) for r in rows]
    logger.info("Models catalog: {} models fetched", len(all_models))

    if not all_models:
        return "# Models Catalog\n\nNo models found.\n"

    model_ids: list[int] = [m.id for m in all_models]

    # Bulk fetch gear and listings — two queries total, counted in Python.
    gear_records: list[dict] = conn.get_model("x_gear").search_read(
        [("x_model_id", "in", model_ids)],
        ["id", "x_model_id", "x_status"],
    )
    logger.info("Models catalog: {} gear records fetched", len(gear_records))

    watching_listings: list[dict] = conn.get_model("x_listing").search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        ["id", "x_model_id"],
    )
    logger.info("Models catalog: {} watching listings fetched", len(watching_listings))

    # Build lookup structures: model_id → {status: count}
    gear_by_model: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for gear in gear_records:
        model_ref = gear.get("x_model_id")
        if isinstance(model_ref, list) and len(model_ref) == 2:
            mid: int = model_ref[0]
            status: str = _scalar(gear.get("x_status"), fallback="unknown")
            gear_by_model[mid][status] += 1

    watching_by_model: dict[int, int] = defaultdict(int)
    for listing in watching_listings:
        model_ref = listing.get("x_model_id")
        if isinstance(model_ref, list) and len(model_ref) == 2:
            watching_by_model[model_ref[0]] += 1

    # Section 1: wanna=True models with zero watching listings.
    wanted_no_listings: list[ModelsRecord] = [
        m for m in all_models if m.x_studio_wanna and watching_by_model[m.id] == 0
    ]

    sections: list[str] = ["# Models Catalog", ""]

    sections.append("## Wanted — No Listings Tracked")
    sections.append("")
    if wanted_no_listings:
        for m in wanted_no_listings:
            name = _scalar(m.x_name, fallback="(unnamed)")
            brand = _label(m.x_studio_partner_id)
            p50 = _scalar(m.x_price_p50)
            sections.append(f"- {name} ({brand}) — p50={p50}")
    else:
        sections.append("*All wanted models have at least one watching listing.*")

    sections.append("")
    sections.append("## Full Catalog")
    sections.append("")

    for model in all_models:
        gear_counts: dict[str, int] = dict(gear_by_model.get(model.id, {}))
        watching_count = watching_by_model[model.id]
        sections.append(_render_model_section(model, gear_counts, watching_count))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
