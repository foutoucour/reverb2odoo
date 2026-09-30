"""MCP tool: fetch a single x_listing record by id.

Returns the listing's model / gear links followed by the same detail block
used by :mod:`odoo_mcp.tools.get_gear` (price, scores, candidate and linked
model flags, URL, notes) — formatted as markdown.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from models import ListingRecord
from odoo_mcp.tools.get_gear import _label, _render_listing_detail, _scalar


def _render_listing_header(listing: ListingRecord) -> str:
    """Render the listing title and its model / gear links."""
    name = _scalar(listing.x_name, fallback="(unnamed)")
    model_name = _label(listing.x_model_id)
    model_id = listing.x_model_id[0] if listing.x_model_id else ""
    gear_name = _label(listing.x_gear_id)
    gear_id = listing.x_gear_id[0] if listing.x_gear_id else ""

    lines: list[str] = [f"# {name}", f"**Model**: {model_name} (id={model_id})"]
    if listing.x_gear_id:
        lines.append(f"**Gear**: {gear_name} (id={gear_id})")
    return "\n".join(lines)


def run(conn: odoolib.main.Connection, listing_id: int) -> str:
    """Fetch a single x_listing record by id.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    listing_id:
        The numeric id of the x_listing record to fetch.

    Returns
    -------
    str
        Formatted markdown document with the listing details, or a "not found"
        notice when the id does not match any record.
    """
    logger.info("get_listing: fetching x_listing id={}", listing_id)
    # Include archived listings: a lookup by id should not hide closed-out records.
    rows: list[dict] = conn.get_model("x_listing").search_read(
        [("id", "=", listing_id), ("x_active", "in", [True, False])],
        ListingRecord.odoo_fields(),
        limit=1,
    )

    if not rows:
        return f"No listing found with id: **{listing_id}**"

    listing = ListingRecord.from_odoo(rows[0])
    logger.info("get_listing: found listing '{}'", listing.x_name)

    return "\n".join([_render_listing_header(listing), "", _render_listing_detail(listing)])
