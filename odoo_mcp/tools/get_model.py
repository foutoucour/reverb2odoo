"""MCP tool: fetch a full x_models spec by name or id.

Returns the model spec, all linked x_gear grouped by status, and all linked
x_listing records grouped by status.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from models import GearRecord, ListingRecord, ModelsRecord

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(m2o: tuple[int, str] | None) -> str:
    """Extract display name from a normalised many2one value."""
    return m2o[1] if m2o else ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None/empty, in which case return fallback."""
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _render_model_spec(model: ModelsRecord, family_names: list[str]) -> str:
    """Render the core x_models fields as a markdown spec block."""
    name = _scalar(model.x_name, fallback="(unnamed)")
    brand = _label(model.x_studio_partner_id)
    model_type = _scalar(model.x_studio_model_type)
    wanna = model.x_studio_wanna or False
    scale = _scalar(model.x_studio_scale)
    neck_feel = _label(model.x_studio_guitar_neck_feel_id)
    finish = _label(model.x_studio_finish)
    fretboard = _label(model.x_studio_fretboard_1)
    p25 = _scalar(model.x_price_p25)
    p50 = _scalar(model.x_price_p50)
    p75 = _scalar(model.x_price_p75)

    family = ", ".join(family_names) if family_names else ""
    wanna_str = "yes" if wanna else "no"

    lines: list[str] = [
        f"# {name} — {brand}",
        f"**Type**: {model_type} | **Wanna**: {wanna_str} | **Scale**: {scale}",
        f"**Neck**: {neck_feel} | **Finish**: {finish} | **Fretboard**: {fretboard}",
    ]
    if family:
        lines.append(f"**Construction**: {family}")
    lines.append(f"**Price brackets**: p25={p25} | p50={p50} | p75={p75}")

    return "\n".join(lines)


def _render_gear_section(gear_records: list[GearRecord]) -> str:
    """Render all x_gear records grouped by status."""
    if not gear_records:
        return "## Gear Instances\n\n*None recorded*"

    by_status: dict[str, list[GearRecord]] = {}
    for gear in gear_records:
        s = _scalar(gear.x_status, fallback="unknown")
        by_status.setdefault(s, []).append(gear)

    lines: list[str] = ["## Gear Instances"]
    for status, items in sorted(by_status.items()):
        lines.append(f"\n### {status} ({len(items)})")
        for gear in items:
            name = _scalar(gear.x_name, fallback="(unnamed)")
            condition = _scalar(gear.x_studio_current_condition)
            intent = _scalar(gear.x_intent)
            lines.append(f"- **{name}** (id={gear.id}) | Condition: {condition} | Intent: {intent}")

    return "\n".join(lines)


def _render_listing_section(listing_records: list[ListingRecord]) -> str:
    """Render all x_listing records grouped by status."""
    if not listing_records:
        return "## Listings\n\n*None recorded*"

    by_status: dict[str, list[ListingRecord]] = {}
    for listing in listing_records:
        s = _scalar(listing.x_status, fallback="unknown")
        by_status.setdefault(s, []).append(listing)

    lines: list[str] = ["## Listings"]
    for status, items in sorted(by_status.items()):
        lines.append(f"\n### {status} ({len(items)})")
        for listing in items:
            price = _scalar(listing.x_price)
            currency = _label(listing.x_currency_id)
            platform = _scalar(listing.x_platform)
            url = _scalar(listing.x_url)
            listing_score = _scalar(listing.x_studio_listing_score)
            price_score = _scalar(listing.x_studio_price_score)
            notes = _scalar(listing.x_studio_notes)

            score_part = (
                f" | scores: listing={listing_score} price={price_score}"
                if listing_score or price_score
                else ""
            )
            lines.append(f"- {price} {currency} on {platform}{score_part}")
            if url:
                lines.append(f"  {url}")
            if notes:
                lines.append(f"  Notes: {notes}")

    return "\n".join(lines)


def _resolve_family_names(conn: odoolib.main.Connection, family_ids: list[int]) -> list[str]:
    """Resolve x_guitar_familly ids to display names."""
    if not family_ids:
        return []
    rows = conn.get_model("x_guitar_familly").search_read([("id", "in", family_ids)], ["x_name"])
    return [str(r.get("x_name") or "") for r in rows if r.get("x_name")]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(conn: odoolib.main.Connection, name_or_id: str) -> str:
    """Fetch a single x_models record by name or numeric id, with full details.

    When ``name_or_id`` is numeric, searches by id. Otherwise performs an
    ilike search on ``x_name``.

    Returns the model spec, all linked x_gear (all statuses), and all linked
    x_listing records (all statuses), each group rendered by status.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    name_or_id:
        A numeric id string (``"42"``) or a name substring to match ilike.

    Returns
    -------
    str
        Formatted markdown document, or a "not found" notice.
    """
    name_or_id = name_or_id.strip()
    models_proxy = conn.get_model("x_models")

    if name_or_id.isdigit():
        logger.info("get_model: searching by id={}", name_or_id)
        domain: list = [("id", "=", int(name_or_id))]
    else:
        logger.info("get_model: searching by name ilike '{}'", name_or_id)
        domain = [("x_name", "ilike", name_or_id)]

    model_rows: list[dict] = models_proxy.search_read(domain, ModelsRecord.odoo_fields(), limit=1)

    if not model_rows:
        return f"No model found matching: **{name_or_id}**"

    model = ModelsRecord.from_odoo(model_rows[0])
    logger.info("get_model: found model id={}", model.id)

    family_names = _resolve_family_names(conn, model.x_studio_guitar_familly_ids)

    gear_proxy = conn.get_model("x_gear")
    gear_rows: list[dict] = gear_proxy.search_read(
        [("x_model_id", "=", model.id)],
        GearRecord.odoo_fields(),
    )
    gear_records = [GearRecord.from_odoo(r) for r in gear_rows]
    logger.debug("get_model: {} gear record(s) linked", len(gear_records))

    listing_proxy = conn.get_model("x_listing")
    listing_rows: list[dict] = listing_proxy.search_read(
        [("x_model_id", "=", model.id)],
        ListingRecord.odoo_fields(),
    )
    listing_records = [ListingRecord.from_odoo(r) for r in listing_rows]
    logger.debug("get_model: {} listing record(s) linked", len(listing_records))

    sections: list[str] = [
        _render_model_spec(model, family_names),
        "",
        _render_gear_section(gear_records),
        "",
        _render_listing_section(listing_records),
    ]

    return "\n".join(sections)
