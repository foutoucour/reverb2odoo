"""MCP tool: search x_gear by brand, model_type, status, and/or intent.

Builds an Odoo domain from the supplied (non-empty) parameters and returns a
compact markdown card list — one line per matching gear record.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from models import GearRecord

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


def _model_ids_for_brand(conn: odoolib.main.Connection, brand: str) -> list[int]:
    """Return x_models ids whose partner name matches brand (case-insensitive)."""
    models_proxy = conn.get_model("x_models")
    records: list[dict] = models_proxy.search_read(
        [("x_studio_partner_id", "ilike", brand)],
        ["id"],
    )
    return [r["id"] for r in records]


def _model_ids_for_type(conn: odoolib.main.Connection, model_type: str) -> list[int]:
    """Return x_models ids whose model_type matches (case-insensitive)."""
    models_proxy = conn.get_model("x_models")
    records: list[dict] = models_proxy.search_read(
        [("x_studio_model_type", "ilike", model_type)],
        ["id"],
    )
    return [r["id"] for r in records]


def _render_card(gear: GearRecord) -> str:
    """Render a single gear record as a compact markdown bullet."""
    name = _scalar(gear.x_name, fallback="(unnamed)")
    status = _scalar(gear.x_status)
    model_name = _label(gear.x_model_id)
    condition = _scalar(gear.x_studio_current_condition)
    intent = _scalar(gear.x_intent)

    return (
        f"- **{name}** [{status}] | Model: {model_name} | Condition: {condition} | Intent: {intent}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    conn: odoolib.main.Connection,
    brand: str = "",
    model_type: str = "",
    status: str = "",
    intent: str = "",
) -> str:
    """Search x_gear by the supplied filters and return compact markdown cards.

    Each non-empty parameter adds a clause to the Odoo search domain.
    Brand and model_type are resolved by first querying x_models, then
    filtering x_gear by the resulting model ids.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    brand:
        Partner name to search for in x_models (ilike).
    model_type:
        Model type value to search for in x_models (ilike).
    status:
        Exact x_gear status value (e.g. ``"watching"``, ``"owned"``, ``"closed"``).
    intent:
        Exact x_gear intent value (e.g. ``"flip"``, ``"keeper"``, ``"unknown"``).

    Returns
    -------
    str
        Markdown string with one bullet per matching gear record, or a
        "no results" notice when nothing matches.
    """
    domain: list = []

    if brand.strip():
        logger.debug("Resolving model ids for brand '{}'", brand)
        model_ids = _model_ids_for_brand(conn, brand.strip())
        if not model_ids:
            logger.info("No x_models found for brand '{}' — returning empty result", brand)
            return f"No gear found matching brand: **{brand}**"
        domain.append(("x_model_id", "in", model_ids))

    if model_type.strip():
        logger.debug("Resolving model ids for model_type '{}'", model_type)
        type_ids = _model_ids_for_type(conn, model_type.strip())
        if not type_ids:
            logger.info(
                "No x_models found for model_type '{}' — returning empty result", model_type
            )
            return f"No gear found matching model_type: **{model_type}**"
        # Intersect with any existing model_id filter when both brand and type supplied.
        if domain and domain[-1][0] == "x_model_id":
            existing_ids = set(domain[-1][2])
            combined = list(existing_ids & set(type_ids))
            domain[-1] = ("x_model_id", "in", combined)
        else:
            domain.append(("x_model_id", "in", type_ids))

    if status.strip():
        domain.append(("x_status", "=", status.strip()))

    if intent.strip():
        domain.append(("x_intent", "=", intent.strip()))

    logger.info("Searching x_gear with domain: {}", domain)
    gear_proxy = conn.get_model("x_gear")
    rows: list[dict] = gear_proxy.search_read(domain, GearRecord.odoo_fields())
    logger.info("search_gear: {} record(s) found", len(rows))

    if not rows:
        return "No gear found matching the supplied filters."

    records = [GearRecord.from_odoo(r) for r in rows]
    lines: list[str] = [f"# Gear Search Results ({len(records)} found)\n"]
    for gear in records:
        lines.append(_render_card(gear))

    return "\n".join(lines)
