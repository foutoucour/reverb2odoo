"""MCP resource: render the user's gear collection as markdown.

Queries x_gear records with status 'owned' or 'for_sale', then fetches the
relevant x_listing records for each gear item and formats everything as a
markdown document suitable for consumption by an LLM context window.
"""

import odoolib
from loguru import logger

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _name(m2o_field: list | bool) -> str:
    """Extract the display name from a many2one field value.

    Odoo returns many2one fields as ``[id, name]`` when set, or ``False``
    when the field is empty.
    """
    if not m2o_field:
        return ""
    return m2o_field[1]


def _val(field: object) -> str:
    """Return the field value as a string, or an empty string when False."""
    if field is False or field is None:
        return ""
    return str(field)


def _render_listing(listing: dict) -> str:
    """Render a single listing as a markdown bullet point."""
    platform = _val(listing.get("x_platform"))
    url = _val(listing.get("x_url"))
    price = _val(listing.get("x_price"))
    currency = _name(listing.get("x_currency_id"))
    score = _val(listing.get("x_studio_listing_score"))
    notes = _val(listing.get("x_studio_notes"))

    price_currency = f"{price} {currency}".strip() if price else ""
    score_part = f" | score: {score}" if score else ""

    line = f"- [{platform}] {url} — {price_currency}{score_part}"

    if notes:
        line += f"\n  Notes: {notes}"

    return line


def _render_gear(gear: dict, listings: list[dict]) -> str:
    """Render a single gear record and its listings as a markdown block."""
    name = _val(gear.get("x_name"))
    status = _val(gear.get("x_status"))
    model_name = _name(gear.get("x_model_id"))
    condition = _val(gear.get("x_condition"))
    intent = _val(gear.get("x_intent"))
    acquiring_price = _val(gear.get("x_studio_acquiring_price"))
    serial_number = _val(gear.get("x_serial_number"))
    notes = _val(gear.get("x_studio_notes"))

    lines: list[str] = []
    lines.append(f"## {name} [{status}]")
    lines.append(f"**Model**: {model_name} | **Condition**: {condition} | **Intent**: {intent}")
    lines.append(f"**Acquired for**: {acquiring_price} | **Serial**: {serial_number}")

    if notes:
        lines.append(f"**Notes**: {notes}")

    lines.append("")
    lines.append("### Listing(s)")

    if listings:
        for listing in listings:
            lines.append(_render_listing(listing))
    else:
        lines.append("*No listings recorded*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render(conn: odoolib.main.Connection) -> str:
    """Return a markdown string representing the user's gear collection.

    Fetches all x_gear records with status 'owned' or 'for_sale', then
    retrieves the associated x_listing records filtered by status:

    - **owned** gear → listings with status ``acquired``
    - **for_sale** gear → listings with status ``for_sale`` or ``sold``

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Formatted markdown document.
    """
    gear_model = conn.get_model("x_gear")
    listing_model = conn.get_model("x_listing")

    logger.info("Fetching gear collection (owned + for_sale)…")
    gear_records: list[dict] = gear_model.search_read(
        [("x_status", "in", ["owned", "for_sale"])],
        GEAR_FIELDS_MCP,
    )
    logger.info("Found {} gear record(s)", len(gear_records))

    lines: list[str] = ["# My Collection\n"]

    for gear in gear_records:
        status = gear.get("x_status")
        listing_statuses = ["acquired"] if status == "owned" else ["for_sale", "sold"]

        logger.debug(
            "Fetching listings for gear id={} (status={}, listing_statuses={})",
            gear["id"],
            status,
            listing_statuses,
        )
        listings: list[dict] = listing_model.search_read(
            [("x_gear_id", "=", gear["id"]), ("x_status", "in", listing_statuses)],
            LISTING_FIELDS_MCP,
        )

        lines.append(_render_gear(gear, listings))

    return "\n".join(lines)
