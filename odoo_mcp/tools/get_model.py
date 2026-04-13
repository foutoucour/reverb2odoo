"""MCP tool: fetch a full x_models spec by name or id.

Returns the model spec, all linked x_gear grouped by status, and all linked
x_listing records grouped by status.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP, MODEL_FIELDS_MCP

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(m2o: list | bool | None) -> str:
    """Extract display name from a many2one [id, name] value, or '' when absent."""
    if isinstance(m2o, list) and len(m2o) == 2:
        return str(m2o[1])
    return ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None, in which case return fallback."""
    if value is False or value is None:
        return fallback
    return str(value)


def _render_model_spec(model: dict) -> str:
    """Render the core x_models fields as a markdown spec block."""
    name = _scalar(model.get("x_name"), fallback="(unnamed)")
    brand = _label(model.get("x_studio_partner_id"))
    model_type = _scalar(model.get("x_studio_model_type"))
    wanna = model.get("x_studio_wanna", False)
    scale = _scalar(model.get("x_studio_scale"))
    neck_feel = _label(model.get("x_studio_guitar_neck_feel_id"))
    finish = _label(model.get("x_studio_finish"))
    fretboard = _label(model.get("x_studio_fretboard_1"))
    p25 = _scalar(model.get("x_studio_p25"))
    p50 = _scalar(model.get("x_studio_p50"))
    p75 = _scalar(model.get("x_studio_p75"))

    # Construction/family is a many2many — stored as list of [id, name] pairs or ids.
    family_raw = model.get("x_studio_guitar_familly_ids") or []
    if family_raw and isinstance(family_raw[0], list):
        family = ", ".join(str(item[1]) for item in family_raw)
    else:
        family = ""

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


def _render_gear_section(gear_records: list[dict]) -> str:
    """Render all x_gear records grouped by status."""
    if not gear_records:
        return "## Gear Instances\n\n*None recorded*"

    by_status: dict[str, list[dict]] = {}
    for gear in gear_records:
        s = _scalar(gear.get("x_status"), fallback="unknown")
        by_status.setdefault(s, []).append(gear)

    lines: list[str] = ["## Gear Instances"]
    for status, items in sorted(by_status.items()):
        lines.append(f"\n### {status} ({len(items)})")
        for gear in items:
            name = _scalar(gear.get("x_name"), fallback="(unnamed)")
            condition = _scalar(gear.get("x_condition"))
            intent = _scalar(gear.get("x_intent"))
            gear_id = gear.get("id", "")
            lines.append(f"- **{name}** (id={gear_id}) | Condition: {condition} | Intent: {intent}")

    return "\n".join(lines)


def _render_listing_section(listing_records: list[dict]) -> str:
    """Render all x_listing records grouped by status."""
    if not listing_records:
        return "## Listings\n\n*None recorded*"

    by_status: dict[str, list[dict]] = {}
    for listing in listing_records:
        s = _scalar(listing.get("x_status"), fallback="unknown")
        by_status.setdefault(s, []).append(listing)

    lines: list[str] = ["## Listings"]
    for status, items in sorted(by_status.items()):
        lines.append(f"\n### {status} ({len(items)})")
        for listing in items:
            price = _scalar(listing.get("x_price"))
            currency = _label(listing.get("x_currency_id"))
            platform = _scalar(listing.get("x_platform"))
            url = _scalar(listing.get("x_url"))
            listing_score = _scalar(listing.get("x_studio_listing_score"))
            price_score = _scalar(listing.get("x_studio_price_score"))
            notes = _scalar(listing.get("x_studio_notes"))

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

    model_records: list[dict] = models_proxy.search_read(domain, MODEL_FIELDS_MCP, limit=1)

    if not model_records:
        return f"No model found matching: **{name_or_id}**"

    model = model_records[0]
    model_id: int = model["id"]
    logger.info("get_model: found model id={}", model_id)

    gear_proxy = conn.get_model("x_gear")
    gear_records: list[dict] = gear_proxy.search_read(
        [("x_model_id", "=", model_id)],
        GEAR_FIELDS_MCP,
    )
    logger.debug("get_model: {} gear record(s) linked", len(gear_records))

    listing_proxy = conn.get_model("x_listing")
    listing_records: list[dict] = listing_proxy.search_read(
        [("x_model_id", "=", model_id)],
        LISTING_FIELDS_MCP,
    )
    logger.debug("get_model: {} listing record(s) linked", len(listing_records))

    sections: list[str] = [
        _render_model_spec(model),
        "",
        _render_gear_section(gear_records),
        "",
        _render_listing_section(listing_records),
    ]

    return "\n".join(sections)
