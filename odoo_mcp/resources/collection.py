"""MCP resource: render the user's gear collection as markdown.

Queries x_gear records with status 'owned' or 'for_sale', then fetches the
relevant x_listing records for each gear item and formats everything as a
markdown document suitable for consumption by an LLM context window.
"""

import odoolib
from loguru import logger

from models import GearRecord, ListingRecord

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _name(m2o: tuple[int, str] | None) -> str:
    return m2o[1] if m2o else ""


def _val(field: object) -> str:
    if field is False or field is None or field == "":
        return ""
    return str(field)


def _render_listing(listing: ListingRecord) -> str:
    """Render a single listing as a markdown bullet point."""
    platform = _val(listing.x_platform)
    url = _val(listing.x_url)
    price = _val(listing.x_price)
    currency = _name(listing.x_currency_id)
    score = _val(listing.x_studio_listing_score)
    notes = _val(listing.x_studio_notes)

    price_currency = f"{price} {currency}".strip() if price else ""
    score_part = f" | score: {score}" if score else ""

    line = f"- [{platform}] {url} — {price_currency}{score_part}"

    if notes:
        line += f"\n  Notes: {notes}"

    return line


def _render_gear(gear: GearRecord, listings: list[ListingRecord]) -> str:
    """Render a single gear record and its listings as a markdown block."""
    name = _val(gear.x_name)
    status = _val(gear.x_status)
    model_name = _name(gear.x_model_id)
    condition = _val(gear.x_studio_current_condition)
    intent = _val(gear.x_intent)
    acquiring_price = _val(gear.x_studio_acquiring_price)
    serial_number = _val(gear.x_serial_number)
    notes = _val(gear.x_studio_notes)

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
    gear_rows: list[dict] = gear_model.search_read(
        [("x_status", "in", ["owned", "for_sale"])],
        GearRecord.odoo_fields(),
    )
    gear_records = [GearRecord.from_odoo(r) for r in gear_rows]
    logger.info("Found {} gear record(s)", len(gear_records))

    lines: list[str] = ["# My Collection\n"]

    for gear in gear_records:
        listing_statuses = ["acquired"] if gear.x_status == "owned" else ["for_sale", "sold"]

        logger.debug(
            "Fetching listings for gear id={} (status={}, listing_statuses={})",
            gear.id,
            gear.x_status,
            listing_statuses,
        )
        listing_rows: list[dict] = listing_model.search_read(
            [("x_gear_id", "=", gear.id), ("x_status", "in", listing_statuses)],
            ListingRecord.odoo_fields(),
        )
        listings = [ListingRecord.from_odoo(r) for r in listing_rows]

        lines.append(_render_gear(gear, listings))

    return "\n".join(lines)
